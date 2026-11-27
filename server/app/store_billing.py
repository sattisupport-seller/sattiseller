"""Покупки в App Store и Google Play: серверная проверка и уведомления магазинов (MASTER_PLAN 3.1–3.2, К-21).

Как устроено (ADR 0012):
- Приложение покупает подписку и присылает идентификатор: transactionId (Apple) или purchaseToken (Google).
- Сервер сам спрашивает магазин (App Store Server API / Google Play Developer API) по TLS со своим ключом
  и только по ответу магазина меняет подписку (`billing.activate_paid` и соседние состояния).
- Уведомления магазинов (App Store Server Notifications V2, Google RTDN) доступ сами не дают: из них берётся
  только идентификатор покупки, после чего сервер перечитывает состояние у магазина. Поддельное уведомление
  приводит лишь к лишнему запросу. Повтор уведомления не обрабатывается дважды (таблица store_notifications).
- Покупка привязана к магазину Satti: appAccountToken (Apple) и obfuscatedAccountId (Google) — UUID,
  выведенный из id магазина и секрета сервера. Чужую покупку к своему магазину не привязать.
- Ключи — только из .env и server/data/secrets/. Без ключей проверка отвечает store_not_configured.
"""

from __future__ import annotations

import base64
import json
import logging
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import httpx
import jwt
from sqlalchemy import DateTime, String, UniqueConstraint, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, Session as DbSession, mapped_column

from .config import settings
from .db import Base
from .errors import ApiError
from .models import Shop
from .timeutil import utc_now

log = logging.getLogger("satti.store")

# Тесты подменяют транспорт записанными ответами магазинов (httpx.MockTransport).
transport: httpx.BaseTransport | None = None

APPLE_HOSTS = {"Production": "https://api.storekit.itunes.apple.com",
               "Sandbox": "https://api.storekit-sandbox.itunes.apple.com"}
GOOGLE_API = "https://androidpublisher.googleapis.com/androidpublisher/v3"
GOOGLE_SCOPE = "https://www.googleapis.com/auth/androidpublisher"

# Статусы App Store Server API (Get All Subscription Statuses)
APPLE_ACTIVE, APPLE_EXPIRED, APPLE_RETRY, APPLE_GRACE, APPLE_REVOKED = 1, 2, 3, 4, 5


def _uid() -> str:
    return uuid.uuid4().hex


class StorePurchase(Base):
    """Покупка подписки в магазине приложений и магазин Satti, к которому она привязана."""

    __tablename__ = "store_purchases"
    __table_args__ = (UniqueConstraint("store", "purchase_key", name="uq_store_purchases_key"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uid)
    store: Mapped[str] = mapped_column(String(16))  # apple | google
    # Apple — originalTransactionId; Google — purchaseToken (длинный, храним целиком)
    purchase_key: Mapped[str] = mapped_column(String(512))
    shop_id: Mapped[str] = mapped_column(String(32), index=True)
    product_id: Mapped[str] = mapped_column(String(128))
    state: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class StoreNotification(Base):
    """Обработанные уведомления магазинов: защита от повторной обработки (идемпотентность)."""

    __tablename__ = "store_notifications"
    __table_args__ = (UniqueConstraint("store", "event_id", name="uq_store_notifications_event"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uid)
    store: Mapped[str] = mapped_column(String(16))
    event_id: Mapped[str] = mapped_column(String(128))  # notificationUUID (Apple) или messageId (Pub/Sub)
    kind: Mapped[str] = mapped_column(String(64))
    result: Mapped[str] = mapped_column(String(32))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


@dataclass
class StoreState:
    """Состояние покупки по ответу магазина — уже в терминах Satti."""

    store: str
    purchase_key: str
    product_id: str
    state: str  # trial | active | cancelled | grace | on_hold | expired | revoked | pending
    access_until: datetime | None
    account_token: str | None
    in_trial: bool
    needs_ack: bool = False
    linked_key: str | None = None  # Google: linkedPurchaseToken прежней покупки (повторная подписка, смена плана)


class StoreNotConfigured(Exception):
    pass


# ---------- общие помощники ----------

def account_token(shop_id: str) -> str:
    """UUID покупки для магазина Satti: appAccountToken (Apple) и obfuscatedAccountId (Google).
    Без секрета сервера его не вычислить, а по нему не узнать id магазина."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"satti:{settings.billing_pepper}:{shop_id}"))


def _client() -> httpx.Client:
    return httpx.Client(transport=transport, timeout=20.0)


def _ms(value) -> datetime | None:
    if value in (None, ""):
        return None
    return datetime.fromtimestamp(int(value) / 1000, tz=timezone.utc)


def _rfc3339(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def jws_payload(token: str) -> dict:
    """Полезная нагрузка JWS без проверки подписи.

    Применяется только к данным, полученным сервером напрямую от Apple по TLS со своим ключом, и к уведомлениям,
    из которых берётся лишь идентификатор для повторного запроса к Apple. Решения о доступе по непроверенным
    данным не принимаются."""
    try:
        part = token.split(".")[1]
        return json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))
    except (IndexError, ValueError) as exc:
        raise ApiError(422, "validation", "Неверный формат ответа магазина.") from exc


def _read_secret(path: str) -> str:
    if not path or not Path(path).exists():
        raise StoreNotConfigured(path or "путь не задан")
    return Path(path).read_text(encoding="utf-8")


# ---------- Apple: App Store Server API ----------

def _apple_token() -> str:
    if not (settings.apple_issuer_id and settings.apple_key_id):
        raise StoreNotConfigured("SATTI_APPLE_ISSUER_ID / SATTI_APPLE_KEY_ID")
    key = _read_secret(settings.apple_private_key_path)
    now = int(time.time())
    return jwt.encode({"iss": settings.apple_issuer_id, "iat": now, "exp": now + 600,
                       "aud": "appstoreconnect-v1", "bid": settings.apple_bundle_id},
                      key, algorithm="ES256", headers={"kid": settings.apple_key_id, "typ": "JWT"})


def _apple_get(path: str) -> dict:
    base = APPLE_HOSTS.get(settings.apple_environment, APPLE_HOSTS["Sandbox"])
    with _client() as c:
        r = c.get(f"{base}{path}", headers={"Authorization": f"Bearer {_apple_token()}"})
    if r.status_code == 404:
        raise ApiError(404, "purchase_not_found", "Покупка не найдена в App Store.")
    if r.status_code >= 400:
        log.warning("app store api %s: %s", path.split("/")[3] if path.count("/") > 2 else path, r.status_code)
        raise ApiError(502, "store_unavailable", "App Store сейчас не отвечает. Попробуйте позже.")
    return r.json()


def apple_state(transaction_id: str) -> StoreState:
    """Текущее состояние подписки по любой транзакции из цепочки (Get All Subscription Statuses)."""
    body = _apple_get(f"/inApps/v1/subscriptions/{transaction_id}")
    if body.get("bundleId") not in (None, settings.apple_bundle_id):
        raise ApiError(422, "purchase_invalid", "Покупка сделана в другом приложении.")
    last = None
    for group in body.get("data", []):
        for item in group.get("lastTransactions", []):
            last = item
    if last is None:
        raise ApiError(404, "purchase_not_found", "Покупка не найдена в App Store.")
    tx = jws_payload(last["signedTransactionInfo"])
    renewal = jws_payload(last["signedRenewalInfo"]) if last.get("signedRenewalInfo") else {}
    if tx.get("bundleId") != settings.apple_bundle_id:
        raise ApiError(422, "purchase_invalid", "Покупка сделана в другом приложении.")
    status = int(last.get("status", 0))
    expires = _ms(tx.get("expiresDate"))
    in_trial = tx.get("offerType") == 1 and tx.get("offerDiscountType") == "FREE_TRIAL"
    if tx.get("revocationDate") or status == APPLE_REVOKED:
        state, until = "revoked", None
    elif status == APPLE_ACTIVE:
        auto = renewal.get("autoRenewStatus", 1)
        state = "trial" if in_trial else ("active" if auto == 1 else "cancelled")
        until = expires
    elif status == APPLE_GRACE:
        state, until = "grace", _ms(renewal.get("gracePeriodExpiresDate")) or expires
    elif status == APPLE_RETRY:
        state, until = "on_hold", None
    else:
        state, until = "expired", expires
    return StoreState(store="apple", purchase_key=str(tx.get("originalTransactionId")),
                      product_id=str(tx.get("productId", "")), state=state, access_until=until,
                      account_token=tx.get("appAccountToken"), in_trial=in_trial)


# ---------- Google: Play Developer API ----------

_google_cache: dict[str, tuple[str, float]] = {}


def google_access_token(scope: str = GOOGLE_SCOPE) -> str:
    """OAuth-токен сервисного аккаунта (JWT bearer). Кэшируется до истечения."""
    cached = _google_cache.get(scope)
    if cached and cached[1] > time.time() + 60:
        return cached[0]
    info = json.loads(_read_secret(settings.google_service_account_path))
    now = int(time.time())
    token_uri = info.get("token_uri", "https://oauth2.googleapis.com/token")
    assertion = jwt.encode({"iss": info["client_email"], "scope": scope, "aud": token_uri,
                            "iat": now, "exp": now + 3600}, info["private_key"], algorithm="RS256")
    with _client() as c:
        r = c.post(token_uri, data={"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                                    "assertion": assertion})
    if r.status_code >= 400:
        log.warning("google oauth: %s", r.status_code)
        raise ApiError(502, "store_unavailable", "Google Play сейчас не отвечает. Попробуйте позже.")
    body = r.json()
    _google_cache[scope] = (body["access_token"], time.time() + int(body.get("expires_in", 3600)))
    return body["access_token"]


GOOGLE_STATES = {
    "SUBSCRIPTION_STATE_ACTIVE": "active",
    "SUBSCRIPTION_STATE_CANCELED": "cancelled",  # отменена, но оплаченный период ещё идёт
    "SUBSCRIPTION_STATE_IN_GRACE_PERIOD": "grace",
    "SUBSCRIPTION_STATE_ON_HOLD": "on_hold",
    "SUBSCRIPTION_STATE_PAUSED": "on_hold",
    "SUBSCRIPTION_STATE_EXPIRED": "expired",
    "SUBSCRIPTION_STATE_PENDING": "pending",
    "SUBSCRIPTION_STATE_PENDING_PURCHASE_CANCELED": "expired",
}


def google_state(purchase_token: str) -> StoreState:
    pkg = settings.google_package_name
    url = f"{GOOGLE_API}/applications/{pkg}/purchases/subscriptionsv2/tokens/{purchase_token}"
    with _client() as c:
        r = c.get(url, headers={"Authorization": f"Bearer {google_access_token()}"})
    if r.status_code in (400, 404, 410):
        raise ApiError(404, "purchase_not_found", "Покупка не найдена в Google Play.")
    if r.status_code >= 400:
        log.warning("play developer api: %s", r.status_code)
        raise ApiError(502, "store_unavailable", "Google Play сейчас не отвечает. Попробуйте позже.")
    body = r.json()
    items = body.get("lineItems") or []
    item = next((i for i in items if i.get("productId") == settings.google_subscription_id), None)
    if item is None:
        raise ApiError(422, "purchase_invalid", "Это не подписка Satti.")
    offer = (item.get("offerDetails") or {}).get("offerId")
    phase = item.get("offerPhase") or {}
    in_trial = "freeTrial" in phase or (not phase and offer == settings.google_trial_offer_id)
    state = GOOGLE_STATES.get(body.get("subscriptionState", ""), "expired")
    if state == "active" and in_trial:
        state = "trial"
    until = _rfc3339(item.get("expiryTime")) if state in ("trial", "active", "cancelled", "grace") else None
    ids = body.get("externalAccountIdentifiers") or {}
    return StoreState(store="google", purchase_key=purchase_token, product_id=item["productId"], state=state,
                      access_until=until, account_token=ids.get("obfuscatedExternalAccountId"), in_trial=in_trial,
                      needs_ack=body.get("acknowledgementState") == "ACKNOWLEDGEMENT_STATE_PENDING",
                      linked_key=body.get("linkedPurchaseToken"))


def google_acknowledge(purchase_token: str) -> None:
    """Подтверждение покупки: без него Google вернёт деньги покупателю через 3 дня."""
    pkg, sub = settings.google_package_name, settings.google_subscription_id
    url = f"{GOOGLE_API}/applications/{pkg}/purchases/subscriptions/{sub}/tokens/{purchase_token}:acknowledge"
    with _client() as c:
        r = c.post(url, headers={"Authorization": f"Bearer {google_access_token()}"}, json={})
    if r.status_code >= 400:
        # не фатально: повторим при следующем уведомлении или проверке; доступ уже выдан по ответу магазина
        log.warning("play acknowledge failed: %s", r.status_code)


# ---------- применение к подписке Satti ----------

def fetch_state(store: str, key: str) -> StoreState:
    try:
        if store == "apple":
            return apple_state(key)
        if store == "google":
            return google_state(key)
    except StoreNotConfigured as exc:
        log.warning("store %s not configured: %s", store, exc)
        raise ApiError(501, "store_not_configured", "Проверка покупок ещё не подключена.") from exc
    raise ApiError(422, "validation", "Неизвестный магазин приложений.")


def apply_state(db: DbSession, shop: Shop, st: StoreState, trial_allowed: bool) -> None:
    """Записывает состояние магазина в подписку Satti. trial_allowed=False — пробный период по правилам Satti
    уже использован (телефон, магазин Kaspi, аккаунт): доступ откроется с первого оплаченного периода."""
    from . import billing

    sub = billing.get_subscription(db, shop.id) or billing.Subscription(shop_id=shop.id, state=st.state)
    if st.in_trial and st.state == "trial" and not trial_allowed:
        sub.state, sub.access_until = "trial_denied", None
    elif st.state in billing.ACCESS_STATES and st.access_until is not None:
        if st.state in ("active", "trial") or sub.state not in billing.ACCESS_STATES:
            billing.activate_paid(db, shop, st.access_until, st.store)  # сбрасывает отсчёт хранения
            sub = billing.get_subscription(db, shop.id)
        sub.state, sub.access_until = st.state, st.access_until
        if st.state == "trial" and sub.trial_started_at is None:
            sub.trial_started_at = utc_now()
    else:
        sub.state = st.state
        if st.state in ("revoked", "on_hold", "pending"):
            sub.access_until = None  # возврат денег или неудачное списание: доступ закрывается сразу
        elif st.access_until is not None:
            sub.access_until = st.access_until
    sub.store = st.store
    db.add(sub)
    db.flush()


def find_purchase(db: DbSession, store: str, key: str | None) -> StorePurchase | None:
    if not key:
        return None
    return db.scalar(select(StorePurchase).where(StorePurchase.store == store, StorePurchase.purchase_key == key))


def shop_for_state(db: DbSession, st: StoreState) -> str | None:
    """Магазин Satti для покупки из уведомления: по самой покупке или по прежней (linkedPurchaseToken)."""
    row = find_purchase(db, st.store, st.purchase_key) or find_purchase(db, st.store, st.linked_key)
    return row.shop_id if row is not None else None


def bind_purchase(db: DbSession, shop: Shop, st: StoreState) -> StorePurchase:
    """Покупка — одному магазину Satti. Чужой appAccountToken или покупка другого магазина — отказ."""
    if st.account_token is not None and st.account_token != account_token(shop.id):
        raise ApiError(409, "purchase_other_account", "Эта покупка оформлена для другого аккаунта Satti.")
    row = find_purchase(db, st.store, st.purchase_key)
    if row is not None and row.shop_id != shop.id:
        raise ApiError(409, "purchase_other_account", "Эта покупка оформлена для другого аккаунта Satti.")
    if row is None:
        row = StorePurchase(store=st.store, purchase_key=st.purchase_key, shop_id=shop.id,
                            product_id=st.product_id, state=st.state)
        db.add(row)
    row.state, row.product_id, row.updated_at = st.state, st.product_id, utc_now()
    return row


def record_notification(db: DbSession, store: str, event_id: str, kind: str, result: str) -> bool:
    """True — уведомление новое и записано; False — уже обрабатывали (повтор от магазина)."""
    if db.scalar(select(StoreNotification.id).where(StoreNotification.store == store,
                                                     StoreNotification.event_id == event_id)) is not None:
        return False
    db.add(StoreNotification(store=store, event_id=event_id, kind=kind[:64], result=result[:32]))
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        return False
    return True


def apple_notification_key(signed_payload: str) -> tuple[str, str, str | None]:
    """(notificationUUID, тип, originalTransactionId) из уведомления App Store Server Notifications V2."""
    body = jws_payload(signed_payload)
    data = body.get("data") or {}
    kind = body.get("notificationType", "")
    if body.get("subtype"):
        kind = f"{kind}/{body['subtype']}"
    tx = jws_payload(data["signedTransactionInfo"]) if data.get("signedTransactionInfo") else {}
    if data.get("bundleId") not in (None, settings.apple_bundle_id):
        raise ApiError(422, "validation", "Уведомление другого приложения.")
    return str(body.get("notificationUUID", "")), kind, tx.get("originalTransactionId")


def google_notification_key(envelope: dict) -> tuple[str, str, str | None]:
    """(messageId, тип, purchaseToken) из push-сообщения Pub/Sub с RTDN."""
    msg = envelope.get("message") or {}
    try:
        data = json.loads(base64.b64decode(msg.get("data", "")) or b"{}")
    except ValueError as exc:
        raise ApiError(422, "validation", "Неверный формат уведомления.") from exc
    if data.get("packageName") not in (None, settings.google_package_name):
        raise ApiError(422, "validation", "Уведомление другого приложения.")
    if "testNotification" in data:
        return str(msg.get("messageId", "")), "test", None
    sub = data.get("subscriptionNotification")
    if sub:
        return str(msg.get("messageId", "")), f"subscription/{sub.get('notificationType')}", sub.get("purchaseToken")
    voided = data.get("voidedPurchaseNotification")
    if voided:
        return str(msg.get("messageId", "")), "voided", voided.get("purchaseToken")
    return str(msg.get("messageId", "")), "other", None


__all__ = ["StorePurchase", "StoreNotification", "StoreState", "account_token", "fetch_state", "apply_state",
           "bind_purchase", "record_notification", "apple_notification_key", "google_notification_key",
           "google_acknowledge", "jws_payload"]
