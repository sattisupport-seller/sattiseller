"""Вход через Apple и Google (ТЗ 2.1, раздел 5): проверка токена, связь аккаунта, отказы."""

import hashlib
import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from app import social_auth
from app.config import settings

KID = "test-key-1"
APPLE_AUD = "kz.satti.seller"
GOOGLE_AUD = "google-client-id.apps.googleusercontent.com"


@pytest.fixture(scope="module")
def keypair():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def jwks(keypair):
    from jwt.algorithms import RSAAlgorithm

    jwk = RSAAlgorithm.to_jwk(keypair.public_key(), as_dict=True)
    jwk.update({"kid": KID, "alg": "RS256", "use": "sig"})
    return {"keys": [jwk]}


@pytest.fixture(autouse=True)
def providers(monkeypatch, jwks):
    monkeypatch.setattr(settings, "apple_client_id", APPLE_AUD)
    monkeypatch.setattr(settings, "google_client_ids", GOOGLE_AUD)
    monkeypatch.setattr(social_auth, "fetch_jwks", lambda provider: jwks)


def _token(keypair, **claims):
    now = int(time.time())
    base = {"iat": now, "exp": now + 600, "sub": "apple-user-001", "email": "anna@privaterelay.appleid.com",
            "email_verified": "true", "aud": APPLE_AUD, "iss": "https://appleid.apple.com"}
    base.update(claims)
    base = {k: v for k, v in base.items() if v is not None}
    return jwt.encode(base, keypair, algorithm="RS256", headers={"kid": KID})


def test_apple_valid_token_logs_in_and_creates_account(client, keypair):
    r = client.post("/v1/auth/apple", json={"id_token": _token(keypair)})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["user"]["email"] == "anna@privaterelay.appleid.com"
    assert body["needs_shop_setup"] is True
    assert body["access_token"]


def test_same_apple_subject_returns_same_account(client, keypair):
    first = client.post("/v1/auth/apple", json={"id_token": _token(keypair)}).json()["user"]["id"]
    again = client.post("/v1/auth/apple", json={"id_token": _token(keypair, email=None)}).json()["user"]["id"]
    assert first == again


@pytest.mark.parametrize("claims", [
    {"aud": "someone.else.app"},
    {"iss": "https://evil.example"},
    {"exp": int(time.time()) - 3600, "iat": int(time.time()) - 7200},
    {"email_verified": "false"},
])
def test_bad_apple_token_is_refused(client, keypair, claims):
    r = client.post("/v1/auth/apple", json={"id_token": _token(keypair, **claims)})
    assert r.status_code in (400, 401), r.text


def test_token_signed_by_other_key_is_refused(client):
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    r = client.post("/v1/auth/apple", json={"id_token": _token(other)})
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "invalid_token"


def test_nonce_must_match_its_sha256(client, keypair):
    nonce = "raw-nonce-123"
    hashed = hashlib.sha256(nonce.encode()).hexdigest()
    ok = client.post("/v1/auth/apple", json={"id_token": _token(keypair, nonce=hashed), "nonce": nonce})
    assert ok.status_code == 200, ok.text
    bad = client.post("/v1/auth/apple", json={"id_token": _token(keypair, nonce="other"), "nonce": nonce})
    assert bad.status_code == 401


def test_google_login_with_verified_email(client, keypair):
    token = _token(keypair, aud=GOOGLE_AUD, iss="https://accounts.google.com", sub="google-7",
                   email="seller@gmail.com", email_verified=True)
    r = client.post("/v1/auth/google", json={"id_token": token})
    assert r.status_code == 200, r.text
    assert r.json()["user"]["email"] == "seller@gmail.com"


def test_google_unconfigured_is_503(client, keypair, monkeypatch):
    monkeypatch.setattr(settings, "google_client_ids", "")
    r = client.post("/v1/auth/google", json={"id_token": _token(keypair, aud=GOOGLE_AUD,
                                                                  iss="https://accounts.google.com")})
    assert r.status_code == 503


def test_email_code_login_is_off_in_production(client, monkeypatch):
    """К-28: для всех, кроме владельца, вход по почте выключен — код не отправляется и не принимается
    (ответ тот же, что при отправке, чтобы не выдать адрес владельца)."""
    monkeypatch.setattr(settings, "email_login_enabled", False)
    monkeypatch.setattr(settings, "admin_email", "owner-only@example.com")
    r = client.post("/v1/auth/email/start", json={"email": "x@example.com"})
    assert r.status_code == 202
    r = client.post("/v1/auth/email/verify", json={"email": "x@example.com", "code": "123456"})
    assert r.status_code == 400
