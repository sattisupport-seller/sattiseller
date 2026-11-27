"""3.3 (MASTER_PLAN, К-21): Sign in with Apple — обмен authorizationCode на refresh token при входе и отзыв токена
через REST API Apple при удалении аккаунта (требование Apple). Ответы Apple — записанные примеры в формате документации."""

from urllib.parse import parse_qs

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app import apple_tokens
from app.accounts import delete_user_account
from app.config import settings
from app.db import engine
from app.models import User
from app.social_auth import SocialIdentity
from tests.test_social_auth import _token, jwks, keypair, providers  # noqa: F401 — фикстуры входа

SIWA_KEY = ec.generate_private_key(ec.SECP256R1())


class FakeApple:
    def __init__(self, revoke_status=200):
        self.calls: list[tuple[str, dict]] = []
        self.revoke_status = revoke_status

    def handler(self, request: httpx.Request) -> httpx.Response:
        form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
        self.calls.append((str(request.url), form))
        if str(request.url) == apple_tokens.TOKEN_URL:
            if form.get("code") != "good-code":
                return httpx.Response(400, json={"error": "invalid_grant"})
            return httpx.Response(200, json={"access_token": "a.1", "token_type": "Bearer", "expires_in": 3600,
                                             "refresh_token": "r.apple-refresh-1", "id_token": "x"})
        if str(request.url) == apple_tokens.REVOKE_URL:
            return httpx.Response(self.revoke_status)
        return httpx.Response(404)


@pytest.fixture
def apple(monkeypatch, tmp_path):
    pem = SIWA_KEY.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                 serialization.NoEncryption())
    (tmp_path / "siwa.p8").write_bytes(pem)
    monkeypatch.setattr(settings, "apple_team_id", "TEAM123456")
    monkeypatch.setattr(settings, "apple_siwa_key_id", "SIWAKEY001")
    monkeypatch.setattr(settings, "apple_siwa_key_path", str(tmp_path / "siwa.p8"))
    fake = FakeApple()
    monkeypatch.setattr(apple_tokens, "transport", httpx.MockTransport(fake.handler))
    return fake


def _login(client, keypair, sub, email, code="good-code"):  # noqa: F811
    r = client.post("/v1/auth/apple", json={"id_token": _token(keypair, sub=sub, email=email),
                                            "authorization_code": code, "accept_terms": True})
    assert r.status_code == 200, r.text
    return r.json()


def _delete(email):
    with DbSession(engine) as db:
        delete_user_account(db, db.scalar(select(User).where(User.email == email)))


def test_code_is_exchanged_and_refresh_token_stored_encrypted(client, keypair, apple):  # noqa: F811
    _login(client, keypair, "apple-rv-1", "rv1@privaterelay.appleid.com")
    url, form = apple.calls[0]
    assert url == apple_tokens.TOKEN_URL and form["grant_type"] == "authorization_code"
    secret = jwt.decode(form["client_secret"], SIWA_KEY.public_key(), algorithms=["ES256"],
                        audience="https://appleid.apple.com")
    assert secret["iss"] == "TEAM123456" and secret["sub"] == settings.apple_client_id
    assert jwt.get_unverified_header(form["client_secret"])["kid"] == "SIWAKEY001"
    with DbSession(engine) as db:
        link = db.get(SocialIdentity, ("apple", "apple-rv-1"))
        assert link.refresh_token_enc and "apple-refresh" not in link.refresh_token_enc


def test_account_deletion_revokes_apple_token(client, keypair, apple):  # noqa: F811
    _login(client, keypair, "apple-rv-2", "rv2@privaterelay.appleid.com")
    _delete("rv2@privaterelay.appleid.com")
    url, form = apple.calls[-1]
    assert url == apple_tokens.REVOKE_URL
    assert form["token"] == "r.apple-refresh-1" and form["token_type_hint"] == "refresh_token"
    with DbSession(engine) as db:
        assert db.get(SocialIdentity, ("apple", "apple-rv-2")) is None


def test_revoke_failure_does_not_block_deletion(client, keypair, apple):  # noqa: F811
    _login(client, keypair, "apple-rv-3", "rv3@privaterelay.appleid.com")
    apple.revoke_status = 500
    _delete("rv3@privaterelay.appleid.com")
    with DbSession(engine) as db:
        assert db.scalar(select(User).where(User.email == "rv3@privaterelay.appleid.com")) is None


def test_bad_code_does_not_block_login(client, keypair, apple):  # noqa: F811
    _login(client, keypair, "apple-rv-4", "rv4@privaterelay.appleid.com", code="bad-code")
    with DbSession(engine) as db:
        assert db.get(SocialIdentity, ("apple", "apple-rv-4")).refresh_token_enc is None


def test_without_siwa_key_login_and_deletion_work(client, keypair, monkeypatch):  # noqa: F811
    monkeypatch.setattr(settings, "apple_siwa_key_path", "")
    _login(client, keypair, "apple-rv-5", "rv5@privaterelay.appleid.com")
    _delete("rv5@privaterelay.appleid.com")
    assert apple_tokens.configured() is False
