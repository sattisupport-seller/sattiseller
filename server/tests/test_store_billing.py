"""Оплата на моках (MASTER_PLAN 3.1–3.2, К-21): проверка покупок у App Store и Google Play по записанным ответам
(формат — по документации App Store Server API и Google Play Developer API), уведомления магазинов, идемпотентность,
пробный период по правилам Satti (телефон, магазин Kaspi, аккаунт)."""

import base64
import json
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app import billing, store_billing
from app.config import settings
from app.db import engine
from app.models import KaspiConnection
from tests.conftest import confirm_age, login

NOW = datetime.now(timezone.utc)
SIGNER = ec.generate_private_key(ec.SECP256R1())  # подпись «магазина» в примерах: сервер её не проверяет (ADR 0012)


def _ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def _jws(payload: dict) -> str:
    return jwt.encode(payload, SIGNER, algorithm="ES256", headers={"x5c": ["MIIB-sample"]})


class FakeStores:
    """Записанные ответы магазинов. apple[originalTransactionId] и google[purchaseToken] — текущее состояние."""

    def __init__(self):
        self.apple: dict[str, dict] = {}
        self.google: dict[str, dict] = {}
        self.acks: list[str] = []
        self.calls: list[str] = []

    def apple_sub(self, original_id: str, shop_id: str | None, status=1, trial=False, days=14, auto=1,
                  revoked=False, grace_days=None, product=None):
        tx = {"transactionId": original_id + "-t", "originalTransactionId": original_id,
              "bundleId": settings.apple_bundle_id, "productId": product or settings.apple_product_trial,
              "purchaseDate": _ms(NOW), "expiresDate": _ms(NOW + timedelta(days=days)),
              "type": "Auto-Renewable Subscription", "environment": "Sandbox", "inAppOwnershipType": "PURCHASED"}
        if shop_id:
            tx["appAccountToken"] = store_billing.account_token(shop_id)
        if trial:
            tx.update(offerType=1, offerDiscountType="FREE_TRIAL")
        if revoked:
            tx.update(revocationDate=_ms(NOW), revocationReason=0)
        renewal = {"originalTransactionId": original_id, "autoRenewStatus": auto,
                   "productId": tx["productId"], "autoRenewProductId": tx["productId"]}
        if grace_days is not None:
            renewal["gracePeriodExpiresDate"] = _ms(NOW + timedelta(days=grace_days))
        self.apple[original_id] = {
            "environment": "Sandbox", "bundleId": settings.apple_bundle_id, "appAppleId": 1234567890,
            "data": [{"subscriptionGroupIdentifier": "21000001", "lastTransactions": [
                {"originalTransactionId": original_id, "status": status,
                 "signedTransactionInfo": _jws(tx), "signedRenewalInfo": _jws(renewal)}]}]}

    def google_sub(self, token: str, shop_id: str | None, state="SUBSCRIPTION_STATE_ACTIVE", trial=False,
                   days=30, ack="ACKNOWLEDGEMENT_STATE_PENDING", linked=None):
        item = {"productId": settings.google_subscription_id,
                "expiryTime": (NOW + timedelta(days=days)).isoformat().replace("+00:00", "Z"),
                "autoRenewingPlan": {"autoRenewEnabled": True},
                "offerDetails": {"basePlanId": "monthly", "offerId": settings.google_trial_offer_id if trial else None},
                "offerPhase": {"freeTrial": {}} if trial else {"basePrice": {}}}
        body = {"kind": "androidpublisher#subscriptionPurchaseV2", "startTime": NOW.isoformat(),
                "regionCode": "KZ", "subscriptionState": state, "latestOrderId": "GPA.0000-0000-0000-00000",
                "acknowledgementState": ack, "lineItems": [item]}
        if shop_id:
            body["externalAccountIdentifiers"] = {"obfuscatedExternalAccountId": store_billing.account_token(shop_id)}
        if linked:
            body["linkedPurchaseToken"] = linked
        self.google[token] = body

    def handler(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        self.calls.append(url)
        if "/inApps/v1/subscriptions/" in url:
            key = url.rsplit("/", 1)[1]
            return httpx.Response(200, json=self.apple[key]) if key in self.apple else httpx.Response(404, json={})
        if url.startswith("https://oauth2.googleapis.com/token"):
            return httpx.Response(200, json={"access_token": "ya29.test", "expires_in": 3600, "token_type": "Bearer"})
        if url.endswith(":acknowledge"):
            self.acks.append(url.split("/tokens/")[1].split(":")[0])
            return httpx.Response(200, json={})
        if "/subscriptionsv2/tokens/" in url:
            key = url.rsplit("/", 1)[1]
            return httpx.Response(200, json=self.google[key]) if key in self.google else httpx.Response(410, json={})
        return httpx.Response(500)


@pytest.fixture
def stores(monkeypatch, tmp_path):
    apple_key = ec.generate_private_key(ec.SECP256R1()).private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    (tmp_path / "apple.p8").write_bytes(apple_key)
    rsa_key = rsa.generate_private_key(public_exponent=65537, key_size=2048).private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    (tmp_path / "google.json").write_text(json.dumps({
        "type": "service_account", "client_email": "satti@test.iam.gserviceaccount.com",
        "private_key": rsa_key.decode(), "token_uri": "https://oauth2.googleapis.com/token"}), encoding="utf-8")
    for name, value in {"apple_issuer_id": "issuer", "apple_key_id": "KEY123",
                        "apple_private_key_path": str(tmp_path / "apple.p8"),
                        "google_service_account_path": str(tmp_path / "google.json"),
                        "google_rtdn_token": "rtdn-secret", "billing_enforced": True,
                        "billing_test_mode": False, "device_check_mode": "fake"}.items():
        monkeypatch.setattr(settings, name, value)
    fake = FakeStores()
    monkeypatch.setattr(store_billing, "transport", httpx.MockTransport(fake.handler))
    store_billing._google_cache.clear()
    return fake


def _seller(client, email, seller="S-100"):
    tokens = login(client, email)
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    confirm_age(client, headers)
    shop_id = client.post("/v1/shops", headers=headers, json={"name": "Магазин"}).json()["id"]
    if seller:
        with DbSession(engine) as db:
            db.add(KaspiConnection(shop_id=shop_id, seller_id=seller, token_enc="x", price_key=uuid.uuid4().hex))
            db.commit()
    return headers, shop_id


def _verify(client, headers, shop_id, store, pid, phone="phone-1"):
    body = {"store": store, "purchase_id": pid}
    if phone:
        body.update(platform="ios" if store == "apple" else "android", device_token=f"tok-{phone}")
    return client.post(f"/v1/shops/{shop_id}/subscription/verify", headers=headers, json=body)


def _apple_notice(original_id: str, kind: str, subtype: str | None = None, uid: str | None = None) -> dict:
    tx = _jws({"originalTransactionId": original_id, "bundleId": settings.apple_bundle_id})
    payload = {"notificationType": kind, "notificationUUID": uid or str(uuid.uuid4()), "version": "2.0",
               "signedDate": _ms(NOW), "data": {"bundleId": settings.apple_bundle_id, "environment": "Sandbox",
                                                "signedTransactionInfo": tx}}
    if subtype:
        payload["subtype"] = subtype
    return {"signedPayload": _jws(payload)}


def _rtdn(token: str, ntype: int, message_id: str | None = None) -> dict:
    data = {"version": "1.0", "packageName": settings.google_package_name, "eventTimeMillis": str(_ms(NOW)),
            "subscriptionNotification": {"version": "1.0", "notificationType": ntype, "purchaseToken": token,
                                         "subscriptionId": settings.google_subscription_id}}
    return {"message": {"data": base64.b64encode(json.dumps(data).encode()).decode(),
                        "messageId": message_id or uuid.uuid4().hex, "publishTime": NOW.isoformat()},
            "subscription": "projects/satti/subscriptions/rtdn"}


def _overview(client, headers, shop_id) -> int:
    return client.get(f"/v1/shops/{shop_id}/overview", headers=headers).status_code


# ---------- Apple ----------

def test_apple_trial_purchase_gives_access_and_marks_trial(client, stores):
    headers, shop_id = _seller(client, "a1@example.com")
    stores.apple_sub("2000000000000001", shop_id, trial=True)
    r = _verify(client, headers, shop_id, "apple", "2000000000000001")
    assert r.status_code == 200, r.text
    assert r.json()["state"] == "trial" and r.json()["store"] == "apple"
    assert _overview(client, headers, shop_id) == 200
    with DbSession(engine) as db:
        kinds = set(db.scalars(select(billing.BillingMark.kind)).all())
    assert kinds == {"user", "shop", "device"}


def test_apple_restore_same_purchase_keeps_trial(client, stores):
    """«Восстановить покупки» присылает ту же покупку ещё раз — пробный период не превращается в отказ."""
    headers, shop_id = _seller(client, "a1r@example.com")
    stores.apple_sub("2000000000000011", shop_id, trial=True)
    assert _verify(client, headers, shop_id, "apple", "2000000000000011").json()["state"] == "trial"
    again = _verify(client, headers, shop_id, "apple", "2000000000000011", phone=None)
    assert again.status_code == 200 and again.json()["state"] == "trial"


def test_apple_purchase_of_other_account_is_refused(client, stores):
    headers, shop_id = _seller(client, "a2@example.com")
    _, other_shop = _seller(client, "a2b@example.com", seller="S-101")
    stores.apple_sub("2000000000000002", other_shop)  # appAccountToken другого магазина
    r = _verify(client, headers, shop_id, "apple", "2000000000000002")
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "purchase_other_account"


def test_apple_purchase_cannot_be_bound_to_second_shop(client, stores):
    headers, shop_id = _seller(client, "a3@example.com")
    stores.apple_sub("2000000000000003", None)  # приложение не передало appAccountToken
    assert _verify(client, headers, shop_id, "apple", "2000000000000003").status_code == 200
    other, other_shop = _seller(client, "a3b@example.com", seller="S-102")
    r = _verify(client, other, other_shop, "apple", "2000000000000003")
    assert r.status_code == 409


def test_apple_trial_on_used_phone_waits_for_first_payment(client, stores):
    """Магазин сам дал пробный период, но телефон его уже получал: доступ — с первого оплаченного периода."""
    h1, s1 = _seller(client, "a4@example.com", seller="S-103")
    stores.apple_sub("2000000000000004", s1, trial=True)
    assert _verify(client, h1, s1, "apple", "2000000000000004", phone="shared").json()["state"] == "trial"

    h2, s2 = _seller(client, "a4b@example.com", seller="S-104")
    stores.apple_sub("2000000000000005", s2, trial=True)
    r = _verify(client, h2, s2, "apple", "2000000000000005", phone="shared")
    assert r.status_code == 200
    assert _overview(client, h2, s2) == 403
    # прошло 14 дней — первая оплата: уведомление DID_RENEW, сервер перечитывает состояние у Apple
    stores.apple_sub("2000000000000005", s2, trial=False, days=30)
    out = client.post("/v1/store/apple/notifications", json=_apple_notice("2000000000000005", "DID_RENEW"))
    assert out.json()["result"] == "active"
    assert _overview(client, h2, s2) == 200


def test_apple_notification_is_processed_once(client, stores):
    headers, shop_id = _seller(client, "a5@example.com")
    stores.apple_sub("2000000000000006", shop_id)
    assert _verify(client, headers, shop_id, "apple", "2000000000000006").status_code == 200
    notice = _apple_notice("2000000000000006", "DID_RENEW", uid="11111111-2222-3333-4444-555555555555")
    assert client.post("/v1/store/apple/notifications", json=notice).json()["result"] == "active"
    calls = len(stores.calls)
    assert client.post("/v1/store/apple/notifications", json=notice).json()["result"] == "duplicate"
    assert len(stores.calls) == calls  # повтор не обращается к Apple и ничего не меняет


def test_apple_refund_closes_access(client, stores):
    headers, shop_id = _seller(client, "a6@example.com")
    stores.apple_sub("2000000000000007", shop_id)
    _verify(client, headers, shop_id, "apple", "2000000000000007")
    assert _overview(client, headers, shop_id) == 200
    stores.apple_sub("2000000000000007", shop_id, status=5, revoked=True)
    assert client.post("/v1/store/apple/notifications",
                       json=_apple_notice("2000000000000007", "REFUND")).json()["result"] == "revoked"
    assert _overview(client, headers, shop_id) == 403


def test_apple_cancel_keeps_access_until_period_end(client, stores):
    headers, shop_id = _seller(client, "a7@example.com")
    stores.apple_sub("2000000000000008", shop_id)
    _verify(client, headers, shop_id, "apple", "2000000000000008")
    stores.apple_sub("2000000000000008", shop_id, auto=0, days=10)  # автопродление выключено
    r = client.post("/v1/store/apple/notifications",
                    json=_apple_notice("2000000000000008", "DID_CHANGE_RENEWAL_STATUS", "AUTO_RENEW_DISABLED"))
    assert r.json()["result"] == "cancelled"
    assert _overview(client, headers, shop_id) == 200


def test_apple_grace_period_keeps_access(client, stores):
    headers, shop_id = _seller(client, "a8@example.com")
    stores.apple_sub("2000000000000009", shop_id)
    _verify(client, headers, shop_id, "apple", "2000000000000009")
    stores.apple_sub("2000000000000009", shop_id, status=4, days=-1, grace_days=6)
    r = client.post("/v1/store/apple/notifications",
                    json=_apple_notice("2000000000000009", "DID_FAIL_TO_RENEW", "GRACE_PERIOD"))
    assert r.json()["result"] == "grace"
    assert _overview(client, headers, shop_id) == 200
    stores.apple_sub("2000000000000009", shop_id, status=2, days=-1)
    client.post("/v1/store/apple/notifications", json=_apple_notice("2000000000000009", "GRACE_PERIOD_EXPIRED"))
    assert _overview(client, headers, shop_id) == 403


def test_apple_notification_for_unknown_purchase_is_recorded(client, stores):
    stores.apple_sub("2000000000000010", None)
    r = client.post("/v1/store/apple/notifications", json=_apple_notice("2000000000000010", "SUBSCRIBED"))
    assert r.status_code == 200 and r.json()["result"] == "unknown_purchase"


# ---------- Google ----------

def test_google_trial_purchase_is_verified_and_acknowledged(client, stores):
    headers, shop_id = _seller(client, "g1@example.com", seller="S-200")
    stores.google_sub("gp-token-1", shop_id, trial=True)
    r = _verify(client, headers, shop_id, "google", "gp-token-1")
    assert r.status_code == 200, r.text
    assert r.json()["state"] == "trial" and r.json()["store"] == "google"
    assert stores.acks == ["gp-token-1"]  # без подтверждения Google вернёт деньги через 3 дня
    assert _overview(client, headers, shop_id) == 200


def test_google_rtdn_requires_secret(client, stores):
    r = client.post("/v1/store/google/rtdn?token=wrong", json=_rtdn("gp-token-x", 2))
    assert r.status_code == 403


def test_google_rtdn_on_hold_closes_access_and_duplicate_is_ignored(client, stores):
    headers, shop_id = _seller(client, "g2@example.com", seller="S-201")
    stores.google_sub("gp-token-2", shop_id, ack="ACKNOWLEDGEMENT_STATE_ACKNOWLEDGED")
    _verify(client, headers, shop_id, "google", "gp-token-2")
    stores.google_sub("gp-token-2", shop_id, state="SUBSCRIPTION_STATE_ON_HOLD", days=-1,
                      ack="ACKNOWLEDGEMENT_STATE_ACKNOWLEDGED")
    msg = _rtdn("gp-token-2", 5, message_id="m-1")  # SUBSCRIPTION_ON_HOLD
    assert client.post("/v1/store/google/rtdn?token=rtdn-secret", json=msg).json()["result"] == "on_hold"
    assert _overview(client, headers, shop_id) == 403
    assert client.post("/v1/store/google/rtdn?token=rtdn-secret", json=msg).json()["result"] == "duplicate"


def test_google_canceled_keeps_access_until_expiry(client, stores):
    headers, shop_id = _seller(client, "g3@example.com", seller="S-202")
    stores.google_sub("gp-token-3", shop_id)
    _verify(client, headers, shop_id, "google", "gp-token-3")
    stores.google_sub("gp-token-3", shop_id, state="SUBSCRIPTION_STATE_CANCELED", days=12)
    r = client.post("/v1/store/google/rtdn?token=rtdn-secret", json=_rtdn("gp-token-3", 3))  # CANCELED
    assert r.json()["result"] == "cancelled"
    assert _overview(client, headers, shop_id) == 200


def test_google_resubscribe_with_linked_token_goes_to_same_shop(client, stores):
    headers, shop_id = _seller(client, "g4@example.com", seller="S-203")
    stores.google_sub("gp-old", shop_id, ack="ACKNOWLEDGEMENT_STATE_ACKNOWLEDGED")
    _verify(client, headers, shop_id, "google", "gp-old")
    stores.google_sub("gp-new", None, linked="gp-old", ack="ACKNOWLEDGEMENT_STATE_ACKNOWLEDGED")
    r = client.post("/v1/store/google/rtdn?token=rtdn-secret", json=_rtdn("gp-new", 4))  # PURCHASED
    assert r.json()["result"] == "active"
    with DbSession(engine) as db:
        rows = db.scalars(select(store_billing.StorePurchase.shop_id)
                          .where(store_billing.StorePurchase.purchase_key == "gp-new")).all()
    assert rows == [shop_id]


def test_google_test_notification_is_accepted(client, stores):
    data = {"version": "1.0", "packageName": settings.google_package_name, "testNotification": {"version": "1.0"}}
    msg = {"message": {"data": base64.b64encode(json.dumps(data).encode()).decode(), "messageId": "t-1"}}
    assert client.post("/v1/store/google/rtdn?token=rtdn-secret", json=msg).json()["result"] == "ignored"


# ---------- предложение и демо ----------

def test_offer_before_kaspi_has_no_trial(client, stores):
    headers, shop_id = _seller(client, "o1@example.com", seller=None)
    r = client.post(f"/v1/shops/{shop_id}/subscription/offer", headers=headers,
                    json={"platform": "ios", "device_token": "tok-o1"})
    assert r.status_code == 200
    body = r.json()
    assert body["trial_available"] is False and body["reason"] == "kaspi_required"
    assert body["account_token"] == store_billing.account_token(shop_id)


def test_demo_cannot_buy(client, stores, demo):
    r = client.post(f"/v1/shops/{demo['shop_id']}/subscription/verify", headers=demo["headers"],
                    json={"store": "apple", "purchase_id": "1"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "demo_purchase"


# ---------- пробный период: телефон, магазин Kaspi, удаление (К-21) ----------

def _offer(client, headers, shop_id, phone):
    return client.post(f"/v1/shops/{shop_id}/subscription/offer", headers=headers,
                       json={"platform": "ios", "device_token": f"tok-{phone}"}).json()


def _delete_user(email):
    from app.accounts import delete_user_account
    from app.models import User

    with DbSession(engine) as db:
        delete_user_account(db, db.scalar(select(User).where(User.email == email)))


def test_second_account_on_same_phone_gets_no_trial(client, stores):
    h1, s1 = _seller(client, "t1@example.com", seller="S-201")
    stores.apple_sub("2000000000000201", s1, trial=True)
    assert _verify(client, h1, s1, "apple", "2000000000000201", phone="p-same").json()["state"] == "trial"
    h2, s2 = _seller(client, "t1b@example.com", seller="S-202")
    body = _offer(client, h2, s2, "p-same")
    assert body["trial_available"] is False and body["reason"] == "trial_used_device"


def test_same_kaspi_shop_new_account_new_phone_gets_no_trial(client, stores):
    h1, s1 = _seller(client, "t2@example.com", seller="S-203")
    stores.apple_sub("2000000000000203", s1, trial=True)
    assert _verify(client, h1, s1, "apple", "2000000000000203", phone="p-a").json()["state"] == "trial"
    _delete_user("t2@example.com")  # магазин освобождается только удалением аккаунта
    h2, s2 = _seller(client, "t2b@example.com", seller="S-203")
    body = _offer(client, h2, s2, "p-b")
    assert body["trial_available"] is False and body["reason"] == "trial_used"


def test_account_deletion_keeps_phone_mark(client, stores):
    h1, s1 = _seller(client, "t3@example.com", seller="S-204")
    stores.apple_sub("2000000000000204", s1, trial=True)
    assert _verify(client, h1, s1, "apple", "2000000000000204", phone="p-del").json()["state"] == "trial"
    _delete_user("t3@example.com")
    h2, s2 = _seller(client, "t3@example.com", seller="S-205")  # та же почта, другой магазин, тот же телефон
    body = _offer(client, h2, s2, "p-del")
    assert body["trial_available"] is False and body["reason"] in ("trial_used", "trial_used_device")
