"""Админ-панель (ТЗ 2.1, раздел 14.1–14.3). Доступ — только владелец (SATTI_ADMIN_EMAIL).

Каждый запрос администратора требует код двухфакторной защиты (TOTP, RFC 6238) в заголовке X-Admin-Code.
Данные пользователя открываются только при его разрешении: POST /me/support-access даёт доступ на 24 часа.
Панель показывает счётчики и управление; тексты диалогов ИИ и данные покупателей здесь не выводятся.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel
from sqlalchemy import DateTime, String, Boolean, func, select
from sqlalchemy.orm import Mapped, Session as DbSession, mapped_column

from .auth import Principal, current_user, get_principal
from .config import settings
from .db import Base, get_session
from .errors import ApiError
from .models import AIConversation, AITurn, Order, Shop, User

SUPPORT_ACCESS_HOURS = 24
FLAG_DEFAULTS = {"kaspi_connection": False, "ai_assistant": True, "subscription": False}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


class AdminTotp(Base):
    """Секрет двухфакторной защиты администратора. Хранится на сервере; в ответах не показывается повторно."""

    __tablename__ = "admin_totp"
    user_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    secret: Mapped[str] = mapped_column(String(64))
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class FeatureFlag(Base):
    __tablename__ = "feature_flags"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


# ---------- TOTP (RFC 6238, HMAC-SHA1, 6 цифр, шаг 30 с) ----------

def totp_code(secret_b32: str, at: float | None = None, step: int = 30, digits: int = 6) -> str:
    key = base64.b32decode(secret_b32.upper() + "=" * (-len(secret_b32) % 8))
    counter = int((at if at is not None else time.time()) // step)
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(value % (10 ** digits)).zfill(digits)


def totp_verify(secret_b32: str, code: str | None, at: float | None = None) -> bool:
    """Принимает текущий код и соседние два (допуск на расхождение часов ±30 с)."""
    if not code or not code.isdigit() or len(code) != 6:
        return False
    now = at if at is not None else time.time()
    return any(hmac.compare_digest(totp_code(secret_b32, now + shift), code) for shift in (-30, 0, 30))


def _admin_user(principal: Principal, db: DbSession) -> User:
    """Владелец панели. Для всех, кто не владелец, панель не существует (404)."""
    if principal.user_id is None or not settings.admin_email:
        raise ApiError(404, "not_found")
    user = current_user(principal, db)
    if user.email.strip().lower() != settings.admin_email:
        raise ApiError(404, "not_found")
    return user


def require_admin(principal: Principal = Depends(get_principal), code: str | None = Header(default=None, alias="X-Admin-Code"),
                  db: DbSession = Depends(get_session)) -> User:
    user = _admin_user(principal, db)
    row = db.get(AdminTotp, user.id)
    if row is None or not row.enabled:
        raise ApiError(403, "two_factor_required", "Включите двухфакторную защиту администратора.")
    if not totp_verify(row.secret, code):
        raise ApiError(403, "admin_code_invalid", "Неверный код двухфакторной защиты.")
    return user


router = APIRouter(prefix="/admin", tags=["админ"])


class CodeIn(BaseModel):
    code: str


class FlagIn(BaseModel):
    enabled: bool


class BlockIn(BaseModel):
    blocked: bool


@router.post("/2fa/setup")
def two_factor_setup(principal: Principal = Depends(get_principal), db: DbSession = Depends(get_session)) -> dict:
    """Создаёт секрет и возвращает его один раз: введите в приложение-аутентификатор и подтвердите кодом."""
    user = _admin_user(principal, db)
    row = db.get(AdminTotp, user.id)
    if row is not None and row.enabled:
        raise ApiError(409, "already_enabled", "Двухфакторная защита уже включена.")
    secret = base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")
    if row is None:
        row = AdminTotp(user_id=user.id, secret=secret, enabled=False)
        db.add(row)
    else:
        row.secret = secret
    db.commit()
    return {"secret": secret, "otpauth": f"otpauth://totp/Satti%20Admin?secret={secret}&issuer=Satti"}


@router.post("/2fa/enable")
def two_factor_enable(body: CodeIn, principal: Principal = Depends(get_principal),
                      db: DbSession = Depends(get_session)) -> dict:
    user = _admin_user(principal, db)
    row = db.get(AdminTotp, user.id)
    if row is None:
        raise ApiError(409, "not_setup", "Сначала создайте секрет: POST /admin/2fa/setup.")
    if not totp_verify(row.secret, body.code):
        raise ApiError(403, "admin_code_invalid", "Неверный код.")
    row.enabled = True
    db.commit()
    return {"enabled": True}


@router.get("/stats")
def stats(_: User = Depends(require_admin), db: DbSession = Depends(get_session)) -> dict:
    """Счётчики без персональных данных (раздел 14.1)."""
    shops = db.scalar(select(func.count()).select_from(Shop).where(Shop.is_demo.is_(False))) or 0
    return {
        "users": db.scalar(select(func.count()).select_from(User)) or 0,
        "shops": shops,
        "orders": db.scalar(select(func.count()).select_from(Order)) or 0,
        "ai_conversations": db.scalar(select(func.count()).select_from(AIConversation)) or 0,
        "ai_questions": db.scalar(select(func.count()).select_from(AITurn)) or 0,
        "blocked_users": db.scalar(select(func.count()).select_from(User).where(User.blocked_at.is_not(None))) or 0,
    }


@router.get("/flags")
def flags_get(_: User = Depends(require_admin), db: DbSession = Depends(get_session)) -> dict:
    stored = {f.key: f.enabled for f in db.scalars(select(FeatureFlag)).all()}
    return {key: stored.get(key, default) for key, default in FLAG_DEFAULTS.items()}


@router.put("/flags/{key}")
def flags_set(key: str, body: FlagIn, _: User = Depends(require_admin), db: DbSession = Depends(get_session)) -> dict:
    if key not in FLAG_DEFAULTS:
        raise ApiError(404, "not_found", "Нет такого флага.")
    row = db.get(FeatureFlag, key)
    if row is None:
        row = FeatureFlag(key=key, enabled=body.enabled, updated_at=_now())
        db.add(row)
    else:
        row.enabled = body.enabled
        row.updated_at = _now()
    db.commit()
    return {key: body.enabled}


@router.get("/users")
def users_list(_: User = Depends(require_admin), db: DbSession = Depends(get_session)) -> dict:
    rows = db.scalars(select(User).order_by(User.created_at.desc()).limit(200)).all()
    items = []
    for u in rows:
        shops_count = db.scalar(select(func.count()).select_from(Shop).where(Shop.owner_user_id == u.id)) or 0
        items.append({
            "id": u.id,
            "email": u.email,
            "created_at": _aware(u.created_at).isoformat(),
            "shops_count": shops_count,
            "blocked": u.blocked_at is not None,
            "support_access_until": (_aware(u.support_access_until).isoformat()
                                     if u.support_access_until and _aware(u.support_access_until) > _now() else None),
        })
    return {"items": items}


@router.post("/users/{user_id}/block")
def user_block(user_id: str, body: BlockIn, _: User = Depends(require_admin), db: DbSession = Depends(get_session)) -> dict:
    user = db.get(User, user_id)
    if user is None:
        raise ApiError(404, "not_found")
    user.blocked_at = _now() if body.blocked else None
    db.commit()
    return {"blocked": body.blocked}


@router.get("/users/{user_id}/shops")
def user_shops(user_id: str, _: User = Depends(require_admin), db: DbSession = Depends(get_session)) -> dict:
    """Магазины пользователя — только при его разрешении на поддержку (раздел 14.3)."""
    user = db.get(User, user_id)
    if user is None:
        raise ApiError(404, "not_found")
    until = _aware(user.support_access_until)
    if until is None or until <= _now():
        raise ApiError(403, "support_access_required", "Пользователь не разрешил доступ поддержки или срок истёк.")
    shops = db.scalars(select(Shop).where(Shop.owner_user_id == user.id)).all()
    return {"items": [{"id": s.id, "name": s.name, "timezone": s.timezone, "language": s.language} for s in shops],
            "access_until": until.isoformat()}


# ---------- разрешение пользователя на доступ поддержки (раздел 14.3) ----------

me_router = APIRouter(tags=["пользователь"])


@me_router.post("/me/support-access")
def grant_support_access(principal: Principal = Depends(get_principal), db: DbSession = Depends(get_session)) -> dict:
    """Пользователь разрешает поддержке посмотреть его магазины на 24 часа."""
    user = current_user(principal, db)
    until = _now() + timedelta(hours=SUPPORT_ACCESS_HOURS)
    user.support_access_until = until
    db.commit()
    return {"access_until": until.isoformat()}


@me_router.delete("/me/support-access")
def revoke_support_access(principal: Principal = Depends(get_principal), db: DbSession = Depends(get_session)) -> dict:
    user = current_user(principal, db)
    user.support_access_until = None
    db.commit()
    return {"access_until": None}


__all__ = ["router", "me_router", "totp_code", "totp_verify"]
