"""Админ-панель (ТЗ 2.1, раздел 14): владелец, двухфакторная защита, флаги, блокировка, доступ поддержки."""

import base64
import time

import pytest

from app.admin import totp_code, totp_verify
from app.config import settings
from tests.conftest import confirm_age, login

ADMIN = "boss@example.com"


@pytest.fixture
def admin_email(monkeypatch):
    monkeypatch.setattr(settings, "admin_email", ADMIN)
    return ADMIN


def _headers(client, email):
    tokens = login(client, email)
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def _enable_2fa(client, headers):
    setup = client.post("/v1/admin/2fa/setup", headers=headers)
    assert setup.status_code == 200, setup.text
    secret = setup.json()["secret"]
    code = totp_code(secret)
    assert client.post("/v1/admin/2fa/enable", headers=headers, json={"code": code}).status_code == 200
    return secret


_SESSIONS: dict[str, str] = {}  # секрет -> сессия панели (в тесте секреты разные)


def _admin_headers(client, headers, secret):
    """Сессия панели: код меняется на сессию один раз. Включение 2FA уже использовало текущий шаг,
    поэтому берём код следующего шага (он в допуске ±30 с)."""
    if secret not in _SESSIONS:
        code = totp_code(secret, at=time.time() + 30)
        r = client.post("/v1/admin/session", headers=headers, json={"code": code})
        assert r.status_code == 200, r.text
        _SESSIONS[secret] = r.json()["admin_session"]
    return {**headers, "X-Admin-Session": _SESSIONS[secret]}


def test_rfc6238_reference_vector():
    # эталон RFC 6238: секрет «12345678901234567890», время 59 с, 8 цифр 94287082 → 6 цифр 287082
    secret = base64.b32encode(b"12345678901234567890").decode().rstrip("=")
    assert totp_code(secret, at=59) == "287082"
    assert totp_verify(secret, "287082", at=59)
    assert not totp_verify(secret, "000000", at=59)
    assert not totp_verify(secret, "28708", at=59)


def test_panel_is_invisible_to_others(client, admin_email):
    headers = _headers(client, "someone@example.com")
    assert client.get("/v1/admin/stats", headers=headers).status_code == 404


def test_admin_needs_2fa_and_code(client, admin_email):
    headers = _headers(client, ADMIN)
    assert client.get("/v1/admin/stats", headers=headers).status_code == 403  # 2FA не включена
    secret = _enable_2fa(client, headers)
    r = client.get("/v1/admin/stats", headers=headers)  # нет сессии панели
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "admin_session_required"
    r = client.post("/v1/admin/session", headers=headers, json={"code": "000000"})  # неверный код
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "admin_code_invalid"
    ok = client.get("/v1/admin/stats", headers=_admin_headers(client, headers, secret))
    assert ok.status_code == 200
    assert set(ok.json()) >= {"users", "shops", "orders", "ai_questions", "blocked_users"}


def test_code_is_accepted_once_and_session_expires(client, admin_email):
    from app.admin import _session_token

    headers = _headers(client, ADMIN)
    secret = _enable_2fa(client, headers)
    code = totp_code(secret, at=time.time() + 30)
    first = client.post("/v1/admin/session", headers=headers, json={"code": code})
    assert first.status_code == 200, first.text
    # тот же код второй раз (в пределах 90 с) — отказ
    again = client.post("/v1/admin/session", headers=headers, json={"code": code})
    assert again.status_code == 403
    assert again.json()["error"]["code"] == "admin_code_used"
    token = first.json()["admin_session"]
    assert client.get("/v1/admin/stats", headers={**headers, "X-Admin-Session": token}).status_code == 200
    # сессия с истёкшим сроком не работает (тот же механизм подписи, срок в прошлом)
    user_id = client.get("/v1/me", headers=headers).json()["id"]
    expired = _session_token(user_id, int(time.time()) - 5)
    assert client.get("/v1/admin/stats", headers={**headers, "X-Admin-Session": expired}).status_code == 403
    # подделанная сессия не работает
    assert client.get("/v1/admin/stats", headers={**headers, "X-Admin-Session": "9999999999.deadbeef"}).status_code == 403


def test_flags_can_be_switched(client, admin_email):
    headers = _headers(client, ADMIN)
    secret = _enable_2fa(client, headers)
    h = _admin_headers(client, headers, secret)
    assert client.get("/v1/admin/flags", headers=h).json()["subscription"] is False
    assert client.put("/v1/admin/flags/subscription", headers=h, json={"enabled": True}).status_code == 200
    assert client.get("/v1/admin/flags", headers=h).json()["subscription"] is True
    assert client.put("/v1/admin/flags/unknown", headers=h, json={"enabled": True}).status_code == 404


def test_block_stops_shop_access_and_unblock_restores(client, admin_email):
    admin = _headers(client, ADMIN)
    secret = _enable_2fa(client, admin)
    ah = _admin_headers(client, admin, secret)

    seller = _headers(client, "seller@example.com")
    confirm_age(client, seller)
    shop = client.post("/v1/shops", headers=seller, json={"name": "Магазин", "timezone": "Asia/Almaty", "language": "ru"}).json()["id"]
    assert client.get(f"/v1/shops/{shop}/overview", headers=seller).status_code == 200

    user_id = client.get("/v1/me", headers=seller).json()["id"]
    assert client.post(f"/v1/admin/users/{user_id}/block", headers=ah, json={"blocked": True}).status_code == 200
    r = client.get(f"/v1/shops/{shop}/overview", headers=seller)
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "account_blocked"

    assert client.post(f"/v1/admin/users/{user_id}/block", headers=ah, json={"blocked": False}).status_code == 200
    assert client.get(f"/v1/shops/{shop}/overview", headers=seller).status_code == 200


def test_support_sees_shops_only_with_24h_consent(client, admin_email):
    admin = _headers(client, ADMIN)
    secret = _enable_2fa(client, admin)
    ah = _admin_headers(client, admin, secret)

    seller = _headers(client, "client@example.com")
    confirm_age(client, seller)
    client.post("/v1/shops", headers=seller, json={"name": "Для поддержки", "timezone": "Asia/Almaty", "language": "ru"})
    user_id = client.get("/v1/me", headers=seller).json()["id"]

    denied = client.get(f"/v1/admin/users/{user_id}/shops", headers=ah)
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "support_access_required"

    grant = client.post("/v1/me/support-access", headers=seller)
    assert grant.status_code == 200
    allowed = client.get(f"/v1/admin/users/{user_id}/shops", headers=ah)
    assert allowed.status_code == 200
    assert [s["name"] for s in allowed.json()["items"]] == ["Для поддержки"]

    client.delete("/v1/me/support-access", headers=seller)
    assert client.get(f"/v1/admin/users/{user_id}/shops", headers=ah).status_code == 403


def test_users_list_shows_access_state(client, admin_email):
    admin = _headers(client, ADMIN)
    secret = _enable_2fa(client, admin)
    ah = _admin_headers(client, admin, secret)
    r = client.get("/v1/admin/users", headers=ah)
    assert r.status_code == 200
    emails = [u["email"] for u in r.json()["items"]]
    assert ADMIN in emails
