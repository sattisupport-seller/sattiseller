"""1.19: согласие с условиями и политикой — галочка при входе, версия и время, повторное согласие при новой версии."""

import uuid

from app.config import settings
from tests.conftest import confirm_age, login


def _auth(tokens):
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def test_login_without_checkbox_asks_for_consent(client):
    tokens = login(client, f"terms-{uuid.uuid4().hex[:8]}@example.invalid", accept_terms=False)
    assert tokens["terms_consent_required"] is True


def test_shop_creation_is_refused_until_terms_are_accepted(client, monkeypatch):
    email = f"terms-{uuid.uuid4().hex[:8]}@example.invalid"
    tokens = login(client, email, accept_terms=False)
    headers = _auth(tokens)
    confirm_age(client, headers)
    body = {"name": "Согласие", "timezone": "Asia/Almaty", "language": "ru"}
    r = client.post("/v1/shops", json=body, headers=headers)
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "terms_consent_required"
    assert client.post("/v1/me/terms", json={"accepted": False}, headers=headers).status_code == 422
    ok = client.post("/v1/me/terms", json={"accepted": True}, headers=headers)
    assert ok.status_code == 200
    assert ok.json()["terms_version"] == settings.legal_version
    assert client.post("/v1/shops", json=body, headers=headers).status_code == 201


def test_new_legal_version_requires_consent_again(client, monkeypatch):
    email = f"terms-{uuid.uuid4().hex[:8]}@example.invalid"
    tokens = login(client, email, accept_terms=False)
    headers = _auth(tokens)
    client.post("/v1/me/terms", json={"accepted": True}, headers=headers)
    monkeypatch.setattr(settings, "legal_version", "2099-01-01-1")
    confirm_age(client, headers)
    r = client.post("/v1/shops", json={"name": "Новая версия", "timezone": "Asia/Almaty", "language": "ru"}, headers=headers)
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "terms_consent_required"
    assert client.get("/v1/app/config").json()["legal_version"] == "2099-01-01-1"


def test_checkbox_at_login_records_version_and_time(client):
    email = f"terms-{uuid.uuid4().hex[:8]}@example.invalid"
    tokens = login(client, email, accept_terms=True)
    assert tokens["terms_consent_required"] is False  # галочка стоит — версия записана
    from sqlalchemy.orm import Session as DbSession
    from app.db import engine
    from app.models import User
    with DbSession(engine) as db:
        user = db.query(User).filter(User.email == email).one()
        assert user.terms_version == settings.legal_version
        assert user.terms_accepted_at is not None
