"""К-28 (решение владельца 27.11): на боевом сервере вход по коду из почты — только для адреса владельца, плюс 2FA."""

from app import ratelimit
from app.config import settings
from tests.conftest import login

OWNER = "owner-k28@example.com"


def _production_like(monkeypatch):
    monkeypatch.setattr(settings, "email_login_enabled", False)
    monkeypatch.setattr(settings, "admin_email", OWNER)
    ratelimit.reset()


def test_owner_can_log_in_by_email_code(client, monkeypatch):
    _production_like(monkeypatch)
    tokens = login(client, OWNER)
    assert tokens["access_token"]


def test_other_address_gets_same_answer_but_no_code(client, monkeypatch):
    _production_like(monkeypatch)
    before = set(settings.outbox_dir.glob("*.eml")) if settings.outbox_dir.exists() else set()
    r = client.post("/v1/auth/email/start", json={"email": "stranger@example.com"})
    assert r.status_code == 202 and r.json()["status"] == "sent"  # не выдаём, чей адрес разрешён
    after = set(settings.outbox_dir.glob("*.eml"))
    assert not any("stranger@example.com" in f.read_text(encoding="utf-8") for f in after - before)
    r = client.post("/v1/auth/email/verify", json={"email": "stranger@example.com", "code": "123456"})
    assert r.status_code == 400 and r.json()["error"]["code"] == "code_invalid"


def test_owner_without_2fa_cannot_open_admin(client, monkeypatch):
    _production_like(monkeypatch)
    tokens = login(client, OWNER)
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    r = client.post("/v1/admin/session", headers=headers, json={"code": "000000"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "two_factor_required"
