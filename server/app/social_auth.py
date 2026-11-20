"""Вход через Apple и Google (ТЗ 2.1, раздел 5). Токен проверяется на сервере по ключам провайдера.

Проверка: подпись RS256 по ключу из JWKS провайдера, издатель (iss), аудитория (aud = наш идентификатор
приложения), срок (exp), nonce (если передан: в токене лежит SHA-256 от nonce, как требует Apple).
Связь с аккаунтом — по паре (провайдер, subject). Для нового провайдера — по email, если он подтверждён.
Проверка с реальными ключами провайдеров — позже (нужны аккаунты владельца, задача 21).
"""

from __future__ import annotations

import hashlib
import json
import time
import urllib.request
from datetime import datetime, timezone

import jwt
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import DateTime, String, select
from sqlalchemy.orm import Mapped, Session as DbSession, mapped_column

from .auth import issue_tokens
from .config import settings
from .db import Base, get_session
from .errors import ApiError
from .models import Shop, User

PROVIDERS = {
    "apple": {
        "keys_url": "https://appleid.apple.com/auth/keys",
        "issuers": {"https://appleid.apple.com"},
    },
    "google": {
        "keys_url": "https://www.googleapis.com/oauth2/v3/certs",
        "issuers": {"https://accounts.google.com", "accounts.google.com"},
    },
}
_JWKS_TTL = 3600
_jwks_cache: dict[str, tuple[float, dict]] = {}


class SocialIdentity(Base):
    __tablename__ = "social_identities"
    provider: Mapped[str] = mapped_column(String(16), primary_key=True)
    subject: Mapped[str] = mapped_column(String(128), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(32), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


def fetch_jwks(provider: str) -> dict:
    """Ключи провайдера с кэшем на час. Ошибка сети — 503, а не вход."""
    now = time.time()
    cached = _jwks_cache.get(provider)
    if cached and now - cached[0] < _JWKS_TTL:
        return cached[1]
    try:
        with urllib.request.urlopen(PROVIDERS[provider]["keys_url"], timeout=10) as resp:  # noqa: S310 — фиксированные адреса
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise ApiError(503, "provider_unavailable", "Не удалось проверить вход. Попробуйте позже.") from exc
    _jwks_cache[provider] = (now, data)
    return data


def _signing_key(jwks: dict, token: str):
    header = jwt.get_unverified_header(token)
    kid = header.get("kid")
    for jwk in jwks.get("keys", []):
        if jwk.get("kid") == kid:
            return jwt.PyJWK(jwk).key
    raise ApiError(401, "invalid_token", "Вход не подтверждён. Войдите ещё раз.")


def _audiences(provider: str) -> list[str]:
    if provider == "apple":
        return [settings.apple_client_id]
    return [c for c in settings.google_client_ids.split(",") if c]


def verify_identity_token(provider: str, token: str, nonce: str | None = None, jwks: dict | None = None) -> dict:
    """Возвращает проверенные утверждения токена или поднимает ApiError 401."""
    if provider not in PROVIDERS:
        raise ApiError(404, "not_found")
    audiences = _audiences(provider)
    if not audiences:
        raise ApiError(503, "provider_not_configured", "Вход через этого провайдера ещё не настроен.")
    keys = jwks if jwks is not None else fetch_jwks(provider)
    try:
        key = _signing_key(keys, token)
        claims = jwt.decode(
            token, key, algorithms=["RS256"], audience=audiences,
            issuer=list(PROVIDERS[provider]["issuers"]),
            options={"require": ["exp", "iat", "sub", "aud", "iss"]},
            leeway=30,
        )
    except ApiError:
        raise
    except jwt.PyJWTError as exc:
        raise ApiError(401, "invalid_token", "Вход не подтверждён. Войдите ещё раз.") from exc
    if nonce is not None:
        expected = hashlib.sha256(nonce.encode("utf-8")).hexdigest()
        if claims.get("nonce") not in (nonce, expected):
            raise ApiError(401, "invalid_token", "Вход не подтверждён. Войдите ещё раз.")
    return claims


def user_for_identity(db: DbSession, provider: str, claims: dict) -> User:
    """Аккаунт по паре (провайдер, subject); для нового провайдера — по подтверждённому email."""
    subject = str(claims["sub"])
    link = db.get(SocialIdentity, (provider, subject))
    if link is not None:
        user = db.get(User, link.user_id)
        if user is not None:
            return user
    email = (claims.get("email") or "").strip().lower()
    verified = str(claims.get("email_verified", "false")).lower() == "true"
    if not email or not verified:
        raise ApiError(400, "email_missing", "Провайдер не передал подтверждённый email. Войдите другим способом.")
    user = db.scalar(select(User).where(User.email == email))
    if user is None:
        user = User(email=email)
        db.add(user)
        db.flush()
    db.add(SocialIdentity(provider=provider, subject=subject, user_id=user.id))
    db.flush()
    return user


class SocialIn(BaseModel):
    id_token: str
    nonce: str | None = None


router = APIRouter(tags=["вход"])


def _login_response(db: DbSession, provider: str, body: SocialIn) -> dict:
    claims = verify_identity_token(provider, body.id_token, nonce=body.nonce)
    user = user_for_identity(db, provider, claims)
    tokens = issue_tokens(db, user_id=user.id)
    db.commit()
    has_shop = db.scalar(select(Shop.id).where(Shop.owner_user_id == user.id).limit(1)) is not None
    return {**tokens, "user": {"id": user.id, "email": user.email}, "needs_shop_setup": not has_shop}


@router.post("/auth/apple")
def auth_apple(body: SocialIn, db: DbSession = Depends(get_session)) -> dict:
    return _login_response(db, "apple", body)


@router.post("/auth/google")
def auth_google(body: SocialIn, db: DbSession = Depends(get_session)) -> dict:
    return _login_response(db, "google", body)


__all__ = ["router", "verify_identity_token", "user_for_identity"]
