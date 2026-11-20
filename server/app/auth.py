"""Сессии, токены и доступ к магазинам (docs/spec.md, раздел 5.3).

Токен доступа — около 15 минут, токен обновления — 30 дней с ротацией. В базе — только хеши.
Демо-сессия привязана к установке приложения и к демо-магазину.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from fastapi import Depends, Header
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from .billing import guard as billing_guard
from .config import settings
from .db import get_session
from .errors import ApiError
from .models import DemoInstallation, Session, Shop, User
from .security import hash_token, new_token


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


@dataclass(frozen=True)
class Principal:
    session_id: str
    user_id: str | None
    demo_install_id: str | None
    demo_shop_id: str | None


def issue_tokens(db: DbSession, *, user_id: str | None = None, demo_install_id: str | None = None,
                 demo_shop_id: str | None = None) -> dict:
    access = new_token()
    refresh = new_token()
    now = utcnow()
    sess = Session(
        user_id=user_id,
        demo_shop_id=demo_shop_id,
        access_hash=hash_token(access),
        refresh_hash=hash_token(refresh),
        access_expires_at=now + timedelta(minutes=settings.access_ttl_minutes),
        refresh_expires_at=now + timedelta(days=settings.refresh_ttl_days),
    )
    db.add(sess)
    db.flush()
    return {
        "access_token": access,
        "refresh_token": refresh,
        "token_type": "bearer",  # nosec B105 — это тип токена по RFC 6750 («bearer»), не пароль
        "expires_in": settings.access_ttl_minutes * 60,
    }


def get_principal(authorization: str | None = Header(default=None),
                  db: DbSession = Depends(get_session)) -> Principal:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise ApiError(401, "unauthorized")
    token = authorization.split(" ", 1)[1].strip()
    sess = db.scalar(select(Session).where(Session.access_hash == hash_token(token)))
    if sess is None or sess.revoked:
        raise ApiError(401, "unauthorized")
    if aware(sess.access_expires_at) < utcnow():
        raise ApiError(401, "token_expired")
    install_id = None
    if sess.demo_shop_id:
        inst = db.scalar(select(DemoInstallation).where(DemoInstallation.shop_id == sess.demo_shop_id))
        install_id = inst.id if inst else None
    return Principal(sess.id, sess.user_id, install_id, sess.demo_shop_id)


def current_user(principal: Principal, db: DbSession) -> User:
    if principal.user_id is None:
        raise ApiError(403, "forbidden", "Этот раздел доступен только в аккаунте.")
    user = db.get(User, principal.user_id)
    if user is None:
        raise ApiError(401, "unauthorized")
    return user


def shop_for(db: DbSession, principal: Principal, shop_id: str, guard_access: bool = True) -> Shop:
    """Магазин, доступный принципалу. guard_access=False — только для экранов подписки (ТЗ 2.1, 9.1)."""
    shop = db.get(Shop, shop_id)
    if shop is None:
        raise ApiError(404, "not_found")
    if shop.is_demo:
        if principal.demo_shop_id != shop.id:
            raise ApiError(403, "forbidden")
    elif not (principal.user_id is not None and shop.owner_user_id == principal.user_id):
        raise ApiError(403, "forbidden")
    if not shop.is_demo:
        from .models import User  # локально: избегаем циклического импорта

        owner = db.get(User, shop.owner_user_id)
        if owner is not None and owner.blocked_at is not None:
            raise ApiError(403, "account_blocked", "Аккаунт заблокирован. Напишите в поддержку.")
    if guard_access:
        billing_guard(db, shop)
    return shop


def ai_consent_state(db: DbSession, principal: Principal) -> tuple[str | None, bool]:
    """Возвращает (версия согласия, активно ли оно)."""
    if principal.user_id:
        user = db.get(User, principal.user_id)
        if user and user.ai_consent_version and user.ai_consent_revoked_at is None:
            return user.ai_consent_version, True
        return (user.ai_consent_version if user else None), False
    if principal.demo_install_id:
        inst = db.get(DemoInstallation, principal.demo_install_id)
        if inst and inst.ai_consent_version and inst.ai_consent_revoked_at is None:
            return inst.ai_consent_version, True
        return (inst.ai_consent_version if inst else None), False
    return None, False


def set_ai_consent(db: DbSession, principal: Principal, granted: bool) -> None:
    now = utcnow()
    if principal.user_id:
        user = db.get(User, principal.user_id)
        if granted:
            user.ai_consent_version = settings.ai_consent_version
            user.ai_consent_at = now
            user.ai_consent_revoked_at = None
        else:
            user.ai_consent_revoked_at = now
    elif principal.demo_install_id:
        inst = db.get(DemoInstallation, principal.demo_install_id)
        if granted:
            inst.ai_consent_version = settings.ai_consent_version
            inst.ai_consent_at = now
            inst.ai_consent_revoked_at = None
        else:
            inst.ai_consent_revoked_at = now
    db.flush()
