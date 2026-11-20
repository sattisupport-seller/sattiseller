"""O2 (отчёт QA): секрет 2FA администратора хранится в базе зашифрованным."""

from sqlalchemy.orm import Session

from app.admin import AdminTotp, _open, totp_code
from app.config import production_config_problems, settings
from app.db import engine
from tests.test_admin import ADMIN, _admin_headers, _enable_2fa, _headers, admin_email  # noqa: F401 (фикстура)


def test_secret_is_not_stored_in_plain_text(client, admin_email):
    headers = _headers(client, ADMIN)
    secret = _enable_2fa(client, headers)
    with Session(engine) as db:
        row = db.query(AdminTotp).one()
        assert row.secret != secret
        assert secret not in row.secret
        assert _open(row.secret) == secret


def test_2fa_still_works_with_encrypted_secret(client, admin_email):
    headers = _headers(client, ADMIN)
    secret = _enable_2fa(client, headers)
    assert client.get("/v1/admin/stats", headers=_admin_headers(client, headers, secret)).status_code == 200
    assert client.get("/v1/admin/stats", headers={**headers, "X-Admin-Session": "000"}).status_code == 403


def test_secret_sealed_with_other_key_is_rejected(client, admin_email, monkeypatch):
    import time as _time

    headers = _headers(client, ADMIN)
    secret = _enable_2fa(client, headers)
    code = totp_code(secret, at=_time.time() + 30)
    with Session(engine) as db:
        token = db.query(AdminTotp).one().secret
    monkeypatch.setattr(settings, "admin_totp_key", "другой-ключ")
    assert _open(token) is None  # ключ сменился → секрет не расшифровать
    r = client.post("/v1/admin/session", headers=headers, json={"code": code})
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "admin_code_invalid"


def test_production_requires_totp_key(monkeypatch):
    monkeypatch.setenv("SATTI_ENV", "production")
    monkeypatch.setattr(settings, "billing_pepper", "настоящий-перец")
    monkeypatch.setattr(settings, "email_login_enabled", False)
    monkeypatch.setattr(settings, "admin_totp_key", "dev-only-change-me")
    assert any("SATTI_TOTP_KEY" in p for p in production_config_problems())
    monkeypatch.setattr(settings, "admin_totp_key", "настоящий-ключ")
    assert not any("SATTI_TOTP_KEY" in p for p in production_config_problems())
