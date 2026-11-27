"""Деактивация аккаунта на 30 дней (К-21, решения владельца 23.11.2026, 01:17 и 01:24): доступ закрыт, фоновое стоит,
восстановление — только с оплаченной подпиской, через 30 дней — полное удаление. Прайс Kaspi никогда не пустой."""

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app import kaspi as kaspi_service
from app.accounts import purge_deactivated
from app.billing import run_retention
from app.db import engine
from app.models import KaspiConnection, Shop, User
from tests.conftest import confirm_age, login
from tests.test_account_deletion import _last_code
from tests.test_store_billing import _verify, stores  # noqa: F401 — фикстура магазинов приложений

NOW = datetime.now(timezone.utc)


def _seller(client, email, seller="D-100"):
    tokens = login(client, email)
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    confirm_age(client, headers)
    shop_id = client.post("/v1/shops", headers=headers, json={"name": "Магазин"}).json()["id"]
    with DbSession(engine) as db:
        db.add(KaspiConnection(shop_id=shop_id, seller_id=seller, token_enc="x", price_key=uuid.uuid4().hex))
        db.commit()
    return headers, shop_id


def _new_code(client, headers, email) -> str:
    """Свежий код удаления: старые письма этому адресу убираем — у писем в одну миллисекунду одинаковое время."""
    from app.config import settings

    for f in settings.outbox_dir.glob("*.eml"):
        if f"To: {email}" in f.read_text(encoding="utf-8"):
            f.unlink()
    assert client.post("/v1/me/deletion/start", headers=headers).status_code == 202
    return _last_code(email)


def _deactivate(client, headers, email):
    r = client.post("/v1/me/deactivation/confirm", headers=headers, json={"code": _new_code(client, headers, email)})
    assert r.status_code == 200, r.text
    return r.json()


def _shift_deactivation(email, days_ago):
    with DbSession(engine) as db:
        user = db.scalar(select(User).where(User.email == email))
        user.deactivated_at = NOW - timedelta(days=days_ago)
        user.delete_after = user.deactivated_at + timedelta(days=30)
        db.commit()


def test_deactivation_closes_access_and_keeps_deletion(client, stores):  # noqa: F811
    email = "d1@example.com"
    headers, shop_id = _seller(client, email)
    stores.apple_sub("3000000000000001", shop_id, days=30)
    assert _verify(client, headers, shop_id, "apple", "3000000000000001").json()["state"] == "active"
    assert client.post("/v1/me/deactivation/confirm", headers=headers, json={"code": "000000"}).status_code == 400

    # время — в момент деактивации, а не при импорте модуля: в полном прогоне тест идёт через минуты (1.15)
    before = datetime.now(timezone.utc)
    out = _deactivate(client, headers, email)
    after = datetime.now(timezone.utc)
    delete_on = datetime.fromisoformat(out["delete_on"])
    assert before + timedelta(days=30) <= delete_on <= after + timedelta(days=30)
    me = client.get("/v1/me", headers=headers).json()
    assert me["deactivated"] is True and me["delete_on"]

    for path in (f"/v1/shops/{shop_id}/overview", f"/v1/shops/{shop_id}/orders", "/v1/me/export"):
        r = client.get(path, headers=headers)
        assert r.status_code == 403 and r.json()["error"]["code"] == "account_deactivated", path
    # экран подписки доступен — через него восстанавливают
    assert client.get(f"/v1/shops/{shop_id}/subscription", headers=headers).status_code == 200
    # полное удаление доступно всегда (Apple 5.1.1(v), Google Play)
    code = _new_code(client, headers, email)
    assert client.post("/v1/me/deletion/confirm", headers=headers, json={"code": code}).status_code == 200
    with DbSession(engine) as db:
        assert db.scalar(select(User).where(User.email == email)) is None


def test_background_stops_and_price_is_never_empty(client, monkeypatch):
    email = "d2@example.com"
    headers, shop_id = _seller(client, email, seller="D-200")
    monkeypatch.setattr("app.config.settings.kaspi_connection_enabled", True)
    from tests.test_kaspi import _set_admin_flag

    _set_admin_flag(True)
    _deactivate(client, headers, email)
    called = []
    monkeypatch.setattr(kaspi_service, "client_for", lambda conn: called.append(conn.shop_id))
    with DbSession(engine) as db:
        done = kaspi_service.sync_due(db, NOW)
        key = db.get(KaspiConnection, shop_id).price_key
    assert shop_id not in called and all(s != shop_id for s, _ in done)

    r = client.get(f"/v1/kaspi/price/{shop_id}/{key}")
    assert r.status_code == 503 and r.headers.get("retry-after") == "3600"
    assert r.content == b""  # ни пустого каталога, ни available="no"


def test_retention_letters_do_not_go_while_deactivated(client):
    email = "d3@example.com"
    headers, shop_id = _seller(client, email, seller="D-300")
    from app.billing import Subscription

    with DbSession(engine) as db:
        db.add(Subscription(shop_id=shop_id, state="active", access_until=NOW - timedelta(days=61),
                            lapsed_at=NOW - timedelta(days=61), store="apple"))
        db.commit()
    _deactivate(client, headers, email)
    with DbSession(engine) as db:
        assert [d for d in run_retention(db, NOW) if d[0] == shop_id] == []


def test_restore_on_day_29_with_paid_subscription(client, stores):  # noqa: F811
    email = "d4@example.com"
    headers, shop_id = _seller(client, email, seller="D-400")
    _deactivate(client, headers, email)
    _shift_deactivation(email, 29)
    r = client.post("/v1/me/reactivation", headers=headers)
    assert r.status_code == 402 and r.json()["error"]["code"] == "subscription_required"

    stores.apple_sub("3000000000000004", shop_id, days=30)  # оплаченный месяц, без пробного периода
    assert _verify(client, headers, shop_id, "apple", "3000000000000004").status_code == 200
    assert client.get("/v1/me", headers=headers).json()["deactivated"] is False
    assert client.get(f"/v1/shops/{shop_id}/overview", headers=headers).status_code == 200


def test_trial_from_store_does_not_restore(client, stores):  # noqa: F811
    """Магазин дал пробный период (новый Apple ID) — восстановление не происходит: нужна оплата (вопрос владельцу)."""
    email = "d5@example.com"
    headers, shop_id = _seller(client, email, seller="D-500")
    _deactivate(client, headers, email)
    stores.apple_sub("3000000000000005", shop_id, trial=True)
    _verify(client, headers, shop_id, "apple", "3000000000000005")
    assert client.get("/v1/me", headers=headers).json()["deactivated"] is True


def test_still_paid_subscription_restores_immediately(client, stores):  # noqa: F811
    """Подписка в магазине сама не отменяется: если она ещё оплачена, восстановление сразу."""
    email = "d6@example.com"
    headers, shop_id = _seller(client, email, seller="D-600")
    stores.apple_sub("3000000000000006", shop_id, days=30)
    _verify(client, headers, shop_id, "apple", "3000000000000006")
    _deactivate(client, headers, email)
    assert client.post("/v1/me/reactivation", headers=headers).json()["status"] == "active"
    assert client.get(f"/v1/shops/{shop_id}/overview", headers=headers).status_code == 200


def test_auto_delete_on_day_31_not_on_day_29(client):
    e1, e2 = "d7@example.com", "d7b@example.com"
    h1, _ = _seller(client, e1, seller="D-700")
    h2, s2 = _seller(client, e2, seller="D-701")
    _deactivate(client, h1, e1)
    _deactivate(client, h2, e2)
    _shift_deactivation(e1, 29)
    _shift_deactivation(e2, 31)
    with DbSession(engine) as db:
        assert purge_deactivated(db, NOW) == 1
    with DbSession(engine) as db:
        assert db.scalar(select(User).where(User.email == e1)) is not None
        assert db.scalar(select(User).where(User.email == e2)) is None
        assert db.get(Shop, s2) is None
