"""Аудит безопасности 27.11, LOW: L2 (email не в ключах лимитов), L3 (шаблон маршрута в журнале),
L5 (ротация ключа токенов), L6 (лимит веб-формы по адресу клиента)."""

from cryptography.fernet import Fernet

from app import ratelimit
from app.config import settings


def test_l2_email_keys_are_hashed():
    k = ratelimit._safe_key("code:anna@example.com")
    assert "anna" not in k and "@" not in k and k.startswith("code:h:")
    assert ratelimit._safe_key("errors:1.2.3.4") == "errors:1.2.3.4"  # без email — как было


def test_l3_route_template_is_logged_not_secret_path(client, monkeypatch):
    from sqlalchemy import select
    from sqlalchemy.orm import Session as DbSession

    from app import api as api_module
    from app.db import engine
    from app.errorlog import AppError

    monkeypatch.setattr(settings, "kaspi_connection_enabled", True)

    def boom(*a, **k):
        raise RuntimeError("сбой")

    monkeypatch.setattr(api_module, "_require_kaspi", boom)
    from fastapi.testclient import TestClient

    from app.main import app
    with TestClient(app, raise_server_exceptions=False) as c:
        assert c.get("/v1/kaspi/price/shop123/SECRETKEY999").status_code == 500
    with DbSession(engine) as db:
        wheres = [e.where for e in db.scalars(select(AppError)).all()]
    assert any("{price_key}" in w for w in wheres)
    assert not any("SECRETKEY999" in w for w in wheres)


def test_l5_old_tokens_still_decrypt_after_key_rotation(monkeypatch):
    from app import kaspi

    old, new = Fernet.generate_key().decode(), Fernet.generate_key().decode()
    monkeypatch.setattr(settings, "kaspi_key", old)
    enc = kaspi.encrypt_token("token-1")
    monkeypatch.setattr(settings, "kaspi_key", f"{new},{old}")  # новый первым, старый — для расшифровки
    assert kaspi.decrypt_token(enc) == "token-1"


def test_l6_web_delete_start_limited_per_client_address(client):
    """После 20 запросов с одного адреса клиента письма с кодом больше не уходят — даже для настоящего аккаунта."""
    from sqlalchemy import select
    from sqlalchemy.orm import Session as DbSession

    from app.db import engine
    from app.models import AuthCode
    from tests.conftest import login

    ratelimit.reset()
    login(client, "l6-real@example.com")
    for i in range(20):
        assert client.post("/delete-account/start", data={"email": f"nobody{i}@example.com"}).status_code == 200
    r = client.post("/delete-account/start", data={"email": "l6-real@example.com"})
    assert r.status_code == 200  # та же страница — не выдаём, есть ли аккаунт и сработал ли лимит
    with DbSession(engine) as db:
        codes = db.scalars(select(AuthCode).where(AuthCode.email == "l6-real@example.com",
                                                  AuthCode.purpose == "delete")).all()
    assert codes == []
    ratelimit.reset()
