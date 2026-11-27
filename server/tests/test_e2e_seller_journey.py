"""К-30 п.2: сквозные сценарии от лица продавца через API (Kaspi, App Store — на моках).

а) новый продавец: вход с галочкой → обучение → Kaspi → 90 дней заказов → себестоимость и остаток → прибыль →
   новый заказ уменьшает остаток → уведомление об остатке → возврат и подтверждение → отчёт и выгрузки →
   помощник → карточка ИИ → пробный период → оплата → деактивация → восстановление с оплатой → удаление;
б) второе устройство того же аккаунта: те же данные, общий лимит помощника;
в) повторный пробный период с того же телефона или для того же магазина Kaspi — нельзя;
г) владелец в админке: вход по почте + 2FA, доступ на 1 месяц, блокировка, окно токена 24 часа.
"""

import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app import kaspi as kaspi_service
from app import ratelimit
from app.admin import totp_code
from app.config import settings
from app.db import engine
from app.kaspi_client import KaspiClient
from app.models import KaspiConnection, User
from tests.conftest import confirm_age, login
from tests.kaspi_mock import DAY_MS
from tests.test_account_deletion import _last_code
from tests.test_seller_access import env  # noqa: F401 — Kaspi на моке
from tests.test_store_billing import _apple_notice, _verify, stores  # noqa: F401 — App Store на моке


def _order(mock, code, created, state, rows, to_warehouse=None):
    ms = int(created.timestamp() * 1000)
    mock.entries[code] = rows
    attrs = {"state": state, "creationDate": ms, "completedDate": ms + DAY_MS, "paymentMode": "PREPAID"}
    if to_warehouse is not None:
        attrs["returnedToWarehouse"] = to_warehouse
    mock.orders.append({"id": code, "type": "orders", "attributes": attrs,
                        "relationships": {"entries": {"links": {"related": f"/orders/{code}/entries"}}}})


def _sync_all(client, headers, shop_id):
    for _ in range(10):  # первая загрузка: 7 дней сразу, остальное — догрузкой до 90 дней
        assert client.post(f"/v1/shops/{shop_id}/kaspi/sync", headers=headers).status_code == 200
        load = client.get(f"/v1/shops/{shop_id}/kaspi/connection", headers=headers).json().get("load") or {}
        if load.get("complete"):
            return
    raise AssertionError("первая загрузка не завершилась")


def _stock(client, headers, shop_id, pid):
    return {i["productId"]: i for i in client.get(f"/v1/shops/{shop_id}/stock", headers=headers).json()["items"]}[pid]


def test_a_new_seller_full_journey(client, env, stores):  # noqa: F811
    ratelimit.reset()
    email = "e2e-journey@example.com"
    # вход с галочкой условий (согласие на ИИ входит в неё, К-24)
    tokens = login(client, email, accept_terms=True)
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    assert client.get("/v1/me", headers=headers).json()["terms_consent_required"] is False
    confirm_age(client, headers)
    shop_id = client.post("/v1/shops", headers=headers, json={"name": "Мой магазин"}).json()["id"]

    # обучение обязательно до Kaspi
    r = client.post(f"/v1/shops/{shop_id}/kaspi/connection", headers=headers, json={"seller_id": "E2E-1", "token": "x" * 20})
    assert r.status_code == 403 and r.json()["error"]["code"] == "onboarding_required"
    client.post("/v1/me/onboarding/complete", headers=headers)
    from tests.kaspi_mock import VALID_TOKEN

    assert client.post(f"/v1/shops/{shop_id}/kaspi/connection", headers=headers,
                       json={"seller_id": "E2E-1", "token": VALID_TOKEN}).status_code == 201
    assert client.get("/v1/me", headers=headers).json()["seller_number"]

    # пробный период — только после Kaspi (App Store, мок)
    offer = client.post(f"/v1/shops/{shop_id}/subscription/offer", headers=headers,
                        json={"platform": "ios", "device_token": "tok-e2e-phone"}).json()
    assert offer["trial_available"] is True
    stores.apple_sub("4000000000000001", shop_id, trial=True)
    assert _verify(client, headers, shop_id, "apple", "4000000000000001", phone="e2e-phone").json()["state"] == "trial"

    # 90 дней заказов
    env.generate(40, now=datetime.now(timezone.utc), days=85, state_cycle=["COMPLETED"], products=2)
    _sync_all(client, headers, shop_id)
    # себестоимость и остаток — оба поля
    missing = client.get(f"/v1/shops/{shop_id}/products/missing-costs", headers=headers).json()["items"]
    assert missing and all(i["needs_cost"] and i["needs_stock"] for i in missing)
    items = [{"product_id": i["product_id"], "purchase": "500", "stock_qty": 12} for i in missing]
    assert client.post(f"/v1/shops/{shop_id}/cost-versions/bulk", headers=headers,
                       json={"items": items, "apply_to_history": True}).status_code == 200
    assert client.get(f"/v1/shops/{shop_id}/products/missing-costs", headers=headers).json()["items"] == []
    # прибыль по магазину и по товарам
    ov = client.get(f"/v1/shops/{shop_id}/overview?period=90d", headers=headers).json()
    assert ov["kpi"]["profit_minor"] is not None and ov["kpi"]["orders_count"] > 0
    products = client.get(f"/v1/shops/{shop_id}/products?period=90d", headers=headers).json()["items"]
    assert products and all(p.get("profit_minor") is not None for p in products)

    # новый заказ после ввода остатка уменьшает остаток; история — нет
    pid = missing[0]["product_id"]
    sku_idx = int(missing[0]["sku"][1:])
    assert _stock(client, headers, shop_id, pid)["current"] == 12
    _order(env, "E2E-NEW", datetime.now(timezone.utc) + timedelta(seconds=2), "COMPLETED",
           [{"id": "ENEW", "idx": sku_idx, "qty": 3, "basePrice": 5000}])
    time.sleep(2.1)
    client.post(f"/v1/shops/{shop_id}/kaspi/sync", headers=headers)
    assert _stock(client, headers, shop_id, pid)["current"] == 9
    # уведомление об остатке (порог 10)
    alerts = client.get(f"/v1/shops/{shop_id}/stock/alerts", headers=headers).json()["items"]
    assert any(a["productId"] == pid and a["level"] == "t10" for a in alerts)

    # возврат без отметки склада → подтверждение → остаток вернулся
    env.set_state("E2E-NEW", "RETURNED")
    with DbSession(engine) as db:
        conn = db.get(KaspiConnection, shop_id)
        kaspi_service.refresh_open_orders(db, conn, KaspiClient(env.token, transport=env.transport(),
                                                                sleep=lambda s: None, min_interval=0),
                                          datetime.now(timezone.utc))
    st = _stock(client, headers, shop_id, pid)
    assert st["pendingReturns"] == 3 and st["current"] == 9
    client.post(f"/v1/shops/{shop_id}/products/{pid}/stock/returns", headers=headers, json={"sellable": True})
    assert _stock(client, headers, shop_id, pid)["current"] == 12

    # отчёт и выгрузки
    x = client.get(f"/v1/shops/{shop_id}/exports/profit.xlsx?period=90d", headers=headers)
    assert x.status_code == 200 and x.content[:2] == b"PK"
    z = client.get("/v1/me/export", headers=headers)
    assert z.status_code == 200 and z.content[:2] == b"PK"

    # помощник и карточка ИИ (без ключа модели — правила и шаблон)
    a = client.post(f"/v1/shops/{shop_id}/ai/ask", headers=headers, json={"question": "Сколько заказов за неделю?"})
    assert a.status_code == 200, a.text
    d = client.post("/v1/ai/product-drafts", headers=headers, data={"shop_id": shop_id, "facts": "Кружка 350 мл"})
    assert d.status_code == 201

    # оплата: первое списание после пробного периода (уведомление App Store)
    stores.apple_sub("4000000000000001", shop_id, trial=False, days=30)
    assert client.post("/v1/store/apple/notifications",
                       json=_apple_notice("4000000000000001", "DID_RENEW")).json()["result"] == "active"

    # деактивация → данные закрыты → восстановление (подписка оплачена) → данные снова видны
    client.post("/v1/me/deletion/start", headers=headers)
    assert client.post("/v1/me/deactivation/confirm", headers=headers, json={"code": _last_code(email)}).status_code == 200
    assert client.get(f"/v1/shops/{shop_id}/overview", headers=headers).status_code == 403
    assert client.post("/v1/me/reactivation", headers=headers).json()["status"] == "active"
    assert client.get(f"/v1/shops/{shop_id}/overview", headers=headers).status_code == 200

    # удаление
    client.post("/v1/me/deletion/start", headers=headers)
    assert client.post("/v1/me/deletion/confirm", headers=headers, json={"code": _last_code(email)}).status_code == 200
    with DbSession(engine) as db:
        assert db.scalar(select(User).where(User.email == email)) is None
    ratelimit.reset()


def test_b_second_device_same_data_and_shared_quota(client, monkeypatch):
    monkeypatch.setattr(settings, "billing_enforced", False)
    monkeypatch.setattr(settings, "ai_daily_limit", 2)
    phone_a = {"Authorization": f"Bearer {login(client, 'e2e-two@example.com')['access_token']}"}
    confirm_age(client, phone_a)
    shop_id = client.post("/v1/shops", headers=phone_a, json={"name": "М"}).json()["id"]
    phone_b = {"Authorization": f"Bearer {login(client, 'e2e-two@example.com')['access_token']}"}
    assert [s["id"] for s in client.get("/v1/shops", headers=phone_b).json()["items"]] == [shop_id]
    assert client.get(f"/v1/shops/{shop_id}/overview", headers=phone_a).json() == \
        client.get(f"/v1/shops/{shop_id}/overview", headers=phone_b).json()
    ask = {"question": "Когда доставка?", "tone": "polite"}
    assert client.post("/v1/ai/reply-drafts", params={"shop_id": shop_id}, headers=phone_a, json=ask).status_code == 201
    assert client.post("/v1/ai/reply-drafts", params={"shop_id": shop_id}, headers=phone_b, json=ask).status_code == 201
    assert client.post("/v1/ai/reply-drafts", params={"shop_id": shop_id}, headers=phone_a, json=ask).status_code == 429


def test_c_no_second_trial_for_same_phone_or_same_kaspi_shop(client, stores):  # noqa: F811
    from tests.test_store_billing import _seller as seller_with_kaspi

    h1, s1 = seller_with_kaspi(client, "e2e-trial1@example.com", seller="E2E-TRIAL")
    stores.apple_sub("4000000000000101", s1, trial=True)
    assert _verify(client, h1, s1, "apple", "4000000000000101", phone="same-phone").json()["state"] == "trial"
    h2, s2 = seller_with_kaspi(client, "e2e-trial2@example.com", seller="E2E-OTHER")  # тот же телефон
    off = client.post(f"/v1/shops/{s2}/subscription/offer", headers=h2,
                      json={"platform": "ios", "device_token": "tok-same-phone"}).json()
    assert off["trial_available"] is False and off["reason"] == "trial_used_device"
    from app.accounts import delete_user_account

    with DbSession(engine) as db:  # магазин Kaspi освобождается только удалением аккаунта
        delete_user_account(db, db.scalar(select(User).where(User.email == "e2e-trial1@example.com")))
    h3, s3 = seller_with_kaspi(client, "e2e-trial3@example.com", seller="E2E-TRIAL")  # тот же магазин, новый телефон
    off = client.post(f"/v1/shops/{s3}/subscription/offer", headers=h3,
                      json={"platform": "ios", "device_token": "tok-new-phone"}).json()
    assert off["trial_available"] is False and off["reason"] == "trial_used"


def test_d_owner_admin_email_2fa_special_access_block_reconnect(client, env, monkeypatch):  # noqa: F811
    from tests.kaspi_mock import VALID_TOKEN

    ratelimit.reset()
    owner = "e2e-owner@example.com"
    monkeypatch.setattr(settings, "admin_email", owner)
    # продавец с подключённым Kaspi (в бою он входит через Apple или Google; здесь — кодом, до режима продакшена)
    seller_tokens = login(client, "e2e-adm-seller@example.com")
    seller = {"Authorization": f"Bearer {seller_tokens['access_token']}"}
    monkeypatch.setattr(settings, "email_login_enabled", False)  # как в продакшене: почта — только для владельца
    confirm_age(client, seller)
    shop_id = client.post("/v1/shops", headers=seller, json={"name": "М"}).json()["id"]
    client.post("/v1/me/onboarding/complete", headers=seller)
    assert client.post(f"/v1/shops/{shop_id}/kaspi/connection", headers=seller,
                       json={"seller_id": "E2E-ADM", "token": VALID_TOKEN}).status_code == 201
    number = client.get("/v1/me", headers=seller).json()["seller_number"]
    # владелец: вход по почте + 2FA
    admin = {"Authorization": f"Bearer {login(client, owner)['access_token']}"}
    secret = client.post("/v1/admin/2fa/setup", headers=admin).json()["secret"]
    assert client.post("/v1/admin/2fa/enable", headers=admin, json={"code": totp_code(secret)}).status_code == 200
    sess = client.post("/v1/admin/session", headers=admin, json={"code": totp_code(secret, at=time.time() + 30)})
    admin = {**admin, "X-Admin-Session": sess.json()["admin_session"]}
    # доступ без подписки на 1 месяц
    assert client.post(f"/v1/admin/sellers/{number}/special-access", headers=admin,
                       json={"months": 1, "confirm": True}).status_code == 200
    sub = client.get(f"/v1/shops/{shop_id}/subscription", headers=seller).json()
    assert sub["state"] == "granted"
    # блокировка и снятие
    client.post(f"/v1/admin/sellers/{number}/block", headers=admin, json={"blocked": True, "confirm": True})
    assert client.get(f"/v1/shops/{shop_id}/overview", headers=seller).json()["error"]["code"] == "account_blocked"
    client.post(f"/v1/admin/sellers/{number}/block", headers=admin, json={"blocked": False, "confirm": True})
    # окно нового токена 24 часа — только тот же магазин
    assert client.post(f"/v1/admin/sellers/{number}/reconnect", headers=admin, json={"confirm": True}).status_code == 200
    assert client.post(f"/v1/shops/{shop_id}/kaspi/connection", headers=seller,
                       json={"seller_id": "OTHER", "token": VALID_TOKEN}).status_code == 409
    assert client.post(f"/v1/shops/{shop_id}/kaspi/connection", headers=seller,
                       json={"seller_id": "E2E-ADM", "token": VALID_TOKEN}).status_code == 201
    ratelimit.reset()
