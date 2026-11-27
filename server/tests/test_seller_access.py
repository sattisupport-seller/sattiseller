"""Номер продавца, токен Kaspi один раз, окно восстановления, блокировка и особые условия (К-21)."""

import time
from datetime import timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app import api as api_module
from app import kaspi as kaspi_service
from app import seller_access
from app.admin import totp_code
from app.config import settings
from app.db import engine
from app.kaspi_client import KaspiClient
from app.models import AuditEvent, KaspiConnection
from app.timeutil import utc_now
from tests.conftest import confirm_age, login
from tests.kaspi_mock import VALID_TOKEN, MockKaspi
from tests.test_kaspi import _set_admin_flag

ADMIN = "owner-admin@example.com"


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setattr(settings, "kaspi_connection_enabled", True)
    monkeypatch.setattr(settings, "admin_email", ADMIN)
    monkeypatch.setattr(settings, "billing_enforced", True)
    _set_admin_flag(True)
    m = MockKaspi()

    def factory(token, **kwargs):
        return KaspiClient(token, transport=m.transport(), sleep=lambda s: None, min_interval=0)

    monkeypatch.setattr(api_module, "KaspiClient", factory)
    monkeypatch.setattr(kaspi_service, "client_for", lambda conn: factory(kaspi_service.decrypt_token(conn.token_enc)))
    return m


def _seller(client, email):
    tokens = login(client, email)
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    confirm_age(client, headers)
    shop_id = client.post("/v1/shops", headers=headers, json={"name": "Магазин"}).json()["id"]
    return headers, shop_id


def _connect(client, headers, shop_id, seller="SELLER-1", token=VALID_TOKEN):
    return client.post(f"/v1/shops/{shop_id}/kaspi/connection", headers=headers,
                       json={"seller_id": seller, "token": token})


def _admin(client):
    tokens = login(client, ADMIN)
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    secret = client.post("/v1/admin/2fa/setup", headers=headers).json()["secret"]
    assert client.post("/v1/admin/2fa/enable", headers=headers, json={"code": totp_code(secret)}).status_code == 200
    r = client.post("/v1/admin/session", headers=headers, json={"code": totp_code(secret, at=time.time() + 30)})
    return {**headers, "X-Admin-Session": r.json()["admin_session"]}


def _number(client, headers) -> str:
    return client.get("/v1/me", headers=headers).json()["seller_number"]


def test_number_is_created_once_on_successful_connection(client, env):
    headers, shop_id = _seller(client, "s1@example.com")
    assert _number(client, headers) is None
    assert _connect(client, headers, shop_id, token="wrong-token-123").status_code == 422  # неудачная попытка не считается
    assert _number(client, headers) is None
    assert _connect(client, headers, shop_id).status_code == 201
    number = _number(client, headers)
    assert number is not None and len(number) == 8 and number.isdigit()
    with DbSession(engine) as db:
        row = db.get(seller_access.SellerNumber, number)
        assert row.seller_hash != "SELLER-1" and "SELLER" not in row.seller_hash  # ID продавца только хешем


def test_token_can_be_connected_only_once(client, env):
    headers, shop_id = _seller(client, "s2@example.com")
    assert _connect(client, headers, shop_id).status_code == 201
    r = _connect(client, headers, shop_id)
    assert r.status_code == 409 and r.json()["error"]["code"] == "kaspi_already_connected"


def test_shop_connected_to_other_account_is_refused(client, env):
    h1, s1 = _seller(client, "s3@example.com")
    assert _connect(client, h1, s1, seller="SHARED").status_code == 201
    h2, s2 = _seller(client, "s3b@example.com")
    r = _connect(client, h2, s2, seller="SHARED")
    assert r.status_code == 409 and r.json()["error"]["code"] == "kaspi_shop_taken"


def test_reconnect_window_accepts_only_same_shop_and_closes(client, env):
    headers, shop_id = _seller(client, "s4@example.com")
    assert _connect(client, headers, shop_id, seller="SAME").status_code == 201
    number = _number(client, headers)
    admin = _admin(client)
    assert client.post(f"/v1/admin/sellers/{number}/reconnect", headers=admin, json={}).status_code == 422  # без подтверждения
    assert client.post(f"/v1/admin/sellers/{number}/reconnect", headers=admin, json={"confirm": True}).status_code == 200
    other = _connect(client, headers, shop_id, seller="OTHER")
    assert other.status_code == 409 and other.json()["error"]["code"] == "kaspi_other_shop"
    assert _connect(client, headers, shop_id, seller="SAME").status_code == 201  # окно открыто — новый токен принят
    again = _connect(client, headers, shop_id, seller="SAME")
    assert again.status_code == 409  # окно одноразовое
    assert _number(client, headers) == number  # номер не меняется


def test_reconnect_window_expires_after_24_hours(client, env):
    headers, shop_id = _seller(client, "s5@example.com")
    _connect(client, headers, shop_id, seller="EXP")
    with DbSession(engine) as db:
        conn = db.get(KaspiConnection, shop_id)
        conn.reconnect_until = utc_now() - timedelta(minutes=1)
        db.commit()
    assert _connect(client, headers, shop_id, seller="EXP").status_code == 409


def test_block_shows_message_and_deletion_stays_possible(client, env):
    headers, shop_id = _seller(client, "s6@example.com")
    _connect(client, headers, shop_id, seller="BLK")
    number = _number(client, headers)
    admin = _admin(client)
    r = client.post(f"/v1/admin/sellers/{number}/block", headers=admin, json={"blocked": True, "confirm": True})
    assert r.status_code == 200 and r.json()["account"] == "blocked"
    blocked = client.get(f"/v1/shops/{shop_id}/overview", headers=headers)
    assert blocked.status_code == 403 and blocked.json()["error"]["code"] == "account_blocked"
    assert client.post("/v1/me/deletion/start", headers=headers).status_code == 202  # удалить можно всегда
    client.post(f"/v1/admin/sellers/{number}/block", headers=admin, json={"blocked": False, "confirm": True})
    assert client.get(f"/v1/shops/{shop_id}/subscription", headers=headers).status_code == 200  # снова пускаем


def test_special_access_opens_shop_without_subscription_and_cancels(client, env):
    headers, shop_id = _seller(client, "s7@example.com")
    _connect(client, headers, shop_id, seller="SPC")
    number = _number(client, headers)
    assert client.get(f"/v1/shops/{shop_id}/overview", headers=headers).status_code == 403  # подписки нет
    admin = _admin(client)
    r = client.post(f"/v1/admin/sellers/{number}/special-access", headers=admin,
                    json={"months": 3, "comment": "партнёр", "confirm": True})
    assert r.status_code == 200, r.text
    assert client.get(f"/v1/shops/{shop_id}/overview", headers=headers).status_code == 200
    sub = client.get(f"/v1/shops/{shop_id}/subscription", headers=headers).json()
    assert sub["state"] == "granted" and sub["access_until"]  # «Доступ открыт до <дата>»
    listing = client.get("/v1/admin/special-access", headers=admin).json()["items"]
    assert listing[0]["seller_id"] == "SPC" and listing[0]["comment"] == "партнёр" and listing[0]["active"]
    assert client.post(f"/v1/admin/sellers/{number}/special-access", headers=admin,
                       json={"months": 2, "confirm": True}).status_code == 422  # только 1, 3 или 6
    client.post(f"/v1/admin/sellers/{number}/special-access/cancel", headers=admin, json={"confirm": True})
    assert client.get(f"/v1/shops/{shop_id}/overview", headers=headers).status_code == 403


def test_special_access_ends_by_itself(client, env):
    headers, shop_id = _seller(client, "s8@example.com")
    _connect(client, headers, shop_id, seller="END")
    number = _number(client, headers)
    admin = _admin(client)
    client.post(f"/v1/admin/sellers/{number}/special-access", headers=admin, json={"months": 1, "confirm": True})
    with DbSession(engine) as db:
        for sa in db.scalars(select(seller_access.SpecialAccess)).all():
            sa.ends_at = utc_now() - timedelta(seconds=1)
        db.commit()
    assert client.get(f"/v1/shops/{shop_id}/overview", headers=headers).status_code == 403


def test_admin_actions_are_owner_only_and_audited(client, env):
    headers, shop_id = _seller(client, "s9@example.com")
    _connect(client, headers, shop_id, seller="AUD")
    number = _number(client, headers)
    # не владелец: панели для него не существует
    assert client.post(f"/v1/admin/sellers/{number}/block", headers=headers,
                       json={"blocked": True, "confirm": True}).status_code in (403, 404)
    admin = _admin(client)
    client.post(f"/v1/admin/sellers/{number}/special-access", headers=admin, json={"months": 6, "confirm": True})
    client.post(f"/v1/admin/sellers/{number}/reconnect", headers=admin, json={"confirm": True})
    with DbSession(engine) as db:
        rows = db.scalars(select(AuditEvent).where(AuditEvent.entity.like(f"seller:{number}%"))).all()
    actions = {r.action for r in rows}
    assert {"special_access_grant", "kaspi_reconnect_window"} <= actions
    assert all(r.actor_id for r in rows)  # кто сделал
    grant = next(r for r in rows if r.action == "special_access_grant")
    assert grant.entity.count(":") == 2  # seller:<номер>:<до какой даты>


def test_deleted_account_keeps_number_and_block_but_not_data(client, env):
    headers, shop_id = _seller(client, "s10@example.com")
    _connect(client, headers, shop_id, seller="DEL")
    number = _number(client, headers)
    admin = _admin(client)
    client.post(f"/v1/admin/sellers/{number}/special-access", headers=admin, json={"months": 1, "confirm": True})
    client.post(f"/v1/admin/sellers/{number}/block", headers=admin, json={"blocked": True, "confirm": True})
    with DbSession(engine) as db:
        from app.accounts import delete_user_account
        from app.models import User

        delete_user_account(db, db.scalar(select(User).where(User.email == "s10@example.com")))
    with DbSession(engine) as db:
        row = db.get(seller_access.SellerNumber, number)
        assert row is not None and row.user_id is None and row.blocked_at is not None
        assert db.scalars(select(seller_access.SpecialAccess)).all() == []
    # новый аккаунт с тем же магазином: блокировка сохраняется
    h2, s2 = _seller(client, "s10b@example.com")
    r = _connect(client, h2, s2, seller="DEL")
    assert r.status_code == 403 and r.json()["error"]["code"] == "account_blocked"


def test_kaspi_cannot_be_disconnected_separately(client, env):
    """Отключить и подключить снова — это была бы замена токена в обход правила «один раз» (К-21, 01:24 и 01:31)."""
    headers, shop_id = _seller(client, "s11@example.com")
    assert _connect(client, headers, shop_id, seller="ONE").status_code == 201
    r = client.delete(f"/v1/shops/{shop_id}/kaspi/connection", headers=headers)
    assert r.status_code == 409 and r.json()["error"]["code"] == "kaspi_disconnect_removed"
    with DbSession(engine) as db:
        assert db.get(KaspiConnection, shop_id) is not None  # подключение осталось
    assert _connect(client, headers, shop_id, seller="ONE").status_code == 409
