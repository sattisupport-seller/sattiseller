"""Админ-панель (ТЗ 2.1, раздел 14.1–14.3). Доступ — только владелец (SATTI_ADMIN_EMAIL).

Администратор вводит код двухфакторной защиты (TOTP, RFC 6238) один раз: POST /admin/session выдаёт сессию
на 30 минут (заголовок X-Admin-Session). Каждый шаг кода принимается только один раз (AUD-15).
Данные пользователя открываются только при его разрешении: POST /me/support-access даёт доступ на 24 часа.
Панель показывает счётчики и управление; тексты диалогов ИИ и данные покупателей здесь не выводятся.
"""

from __future__ import annotations
from datetime import datetime as _dt, timedelta as _td, timezone as _tz

import base64
import hashlib
import hmac
import secrets
import struct
import time

from datetime import datetime, timedelta, timezone
from .timeutil import utc_now

from cryptography.fernet import Fernet, InvalidToken
from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel
from sqlalchemy import Boolean, DateTime, Integer, String, func, select
from sqlalchemy.orm import Mapped, Session as DbSession, mapped_column

from .auth import Principal, current_user, get_principal
from .config import settings
from .db import Base, get_session
from .errors import ApiError
from .models import AIConversation, AITurn, Order, Shop, User

SUPPORT_ACCESS_HOURS = 24
FLAG_DEFAULTS = {"kaspi_connection": False, "ai_assistant": True, "subscription": False, "analytics": False}


def _now() -> datetime:
    return utc_now()


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


class AdminTotp(Base):
    """Секрет двухфакторной защиты администратора. В базе хранится зашифрованным (см. _seal); в ответах не показывается повторно."""

    __tablename__ = "admin_totp"
    user_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    secret: Mapped[str] = mapped_column(String(255))  # шифротекст, не сам секрет
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    last_step: Mapped[int] = mapped_column(Integer, default=0)  # последний принятый шаг TOTP: код не повторяется
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class FeatureFlag(Base):
    __tablename__ = "feature_flags"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


# ---------- шифрование секрета в базе (Fernet, ключ из SATTI_TOTP_KEY) ----------

def _fernet() -> Fernet:
    key = base64.urlsafe_b64encode(hashlib.sha256(settings.admin_totp_key.encode("utf-8")).digest())
    return Fernet(key)


def _seal(secret_b32: str) -> str:
    return _fernet().encrypt(secret_b32.encode("ascii")).decode("ascii")


def _open(token: str) -> str | None:
    """Расшифровывает секрет. None — если ключ сменился или значение повреждено: 2FA нужно настроить заново."""
    try:
        return _fernet().decrypt(token.encode("ascii")).decode("ascii")
    except (InvalidToken, UnicodeError, ValueError):
        return None


# ---------- TOTP (RFC 6238, HMAC-SHA1, 6 цифр, шаг 30 с) ----------

def totp_code(secret_b32: str, at: float | None = None, step: int = 30, digits: int = 6) -> str:
    key = base64.b32decode(secret_b32.upper() + "=" * (-len(secret_b32) % 8))
    counter = int((at if at is not None else time.time()) // step)
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(value % (10 ** digits)).zfill(digits)


def totp_step_matched(secret_b32: str, code: str | None, at: float | None = None) -> int | None:
    """Номер шага (30 с), которому соответствует код; None — код неверен.

    Принимаются текущий шаг и соседние два (допуск на расхождение часов ±30 с).
    """
    if not code or not code.isdigit() or len(code) != 6:
        return None
    now = at if at is not None else time.time()
    for shift in (-30, 0, 30):
        t = now + shift
        if hmac.compare_digest(totp_code(secret_b32, t), code):
            return int(t // 30)
    return None


def totp_verify(secret_b32: str, code: str | None, at: float | None = None) -> bool:
    return totp_step_matched(secret_b32, code, at) is not None


SESSION_TTL_SECONDS = 30 * 60


def _session_token(user_id: str, session_id: str, expires: int) -> str:
    """Подпись включает сессию входа (аудит 27.11, L4): выход из аккаунта гасит и сессию админки."""
    from .security import hash_token

    return f"{expires}.{hash_token(f'admin-session|{user_id}|{session_id}|{expires}')}"


def _check_session_token(token: str | None, user_id: str, session_id: str) -> bool:
    from .security import hash_token

    if not token or "." not in token:
        return False
    exp_text, sig = token.split(".", 1)
    try:
        expires = int(exp_text)
    except ValueError:
        return False
    if expires < int(time.time()):
        return False
    return hmac.compare_digest(sig, hash_token(f"admin-session|{user_id}|{session_id}|{expires}"))


def _accept_new_step(db: DbSession, row: "AdminTotp", step: int) -> None:
    """Шаг TOTP принимается один раз: повторный код (в пределах 90 с) отклоняется.
    Проверка атомарна (аудит 27.11, H1): два параллельных запроса с одним кодом не проходят оба."""
    from sqlalchemy import or_, update

    done = db.execute(update(AdminTotp).where(AdminTotp.user_id == row.user_id,
                                              or_(AdminTotp.last_step.is_(None), AdminTotp.last_step < step))
                      .values(last_step=step)).rowcount
    if not done:
        db.rollback()
        raise ApiError(403, "admin_code_used", "Этот код уже использован. Дождитесь нового кода в приложении.")


TOTP_ATTEMPTS = 10  # попыток кода за 15 минут на администратора (аудит 27.11, H1: перебор 6 цифр)
TOTP_WINDOW = 900


def _limit_totp(db: DbSession, user_id: str) -> None:
    from .ratelimit import allow

    if not allow(f"admin-totp:{user_id}", TOTP_ATTEMPTS, TOTP_WINDOW, db=db):
        try:
            from .mailer import send_owner_alert

            send_owner_alert("Satti: много неверных кодов входа в админку",
                             "За 15 минут исчерпан лимит попыток кода двухфакторной защиты. Если это были не вы — "
                             "смените пароль почты и выйдите из всех сессий.")
        except Exception:  # noqa: BLE001 — оповещение не мешает отказу
            pass
        raise ApiError(429, "admin_code_locked", "Слишком много попыток. Подождите 15 минут.")


def _admin_user(principal: Principal, db: DbSession) -> User:
    """Владелец панели. Для всех, кто не владелец, панель не существует (404)."""
    if principal.user_id is None or not settings.admin_email:
        raise ApiError(404, "not_found")
    user = current_user(principal, db)
    if user.email.strip().lower() != settings.admin_email:
        raise ApiError(404, "not_found")
    return user


def require_admin(principal: Principal = Depends(get_principal),
                  session: str | None = Header(default=None, alias="X-Admin-Session"),
                  db: DbSession = Depends(get_session)) -> User:
    user = _admin_user(principal, db)
    row = db.get(AdminTotp, user.id)
    if row is None or not row.enabled:
        raise ApiError(403, "two_factor_required", "Включите двухфакторную защиту администратора.")
    if not _check_session_token(session, user.id, principal.session_id):
        raise ApiError(403, "admin_session_required", "Введите код двухфакторной защиты, чтобы открыть панель.")
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
        row = AdminTotp(user_id=user.id, secret=_seal(secret), enabled=False)
        db.add(row)
    else:
        row.secret = _seal(secret)
    db.commit()
    return {"secret": secret, "otpauth": f"otpauth://totp/Satti%20Admin?secret={secret}&issuer=Satti"}


@router.post("/2fa/enable")
def two_factor_enable(body: CodeIn, principal: Principal = Depends(get_principal),
                      db: DbSession = Depends(get_session)) -> dict:
    user = _admin_user(principal, db)
    row = db.get(AdminTotp, user.id)
    if row is None:
        raise ApiError(409, "not_setup", "Сначала создайте секрет: POST /admin/2fa/setup.")
    _limit_totp(db, user.id)
    secret = _open(row.secret)
    step = totp_step_matched(secret, body.code) if secret is not None else None
    if step is None:
        raise ApiError(403, "admin_code_invalid", "Неверный код.")
    _accept_new_step(db, row, step)
    row.enabled = True
    db.commit()
    return {"enabled": True}


@router.post("/session")
def open_session(body: CodeIn, principal: Principal = Depends(get_principal),
                 db: DbSession = Depends(get_session)) -> dict:
    """Код двухфакторной защиты меняется на сессию на 30 минут. Один и тот же код второй раз не принимается."""
    user = _admin_user(principal, db)
    row = db.get(AdminTotp, user.id)
    if row is None or not row.enabled:
        raise ApiError(403, "two_factor_required", "Включите двухфакторную защиту администратора.")
    _limit_totp(db, user.id)
    secret = _open(row.secret)
    step = totp_step_matched(secret, body.code) if secret is not None else None
    if step is None:
        raise ApiError(403, "admin_code_invalid", "Неверный код двухфакторной защиты.")
    _accept_new_step(db, row, step)
    db.commit()
    expires = int(time.time()) + SESSION_TTL_SECONDS
    return {"admin_session": _session_token(user.id, principal.session_id, expires), "expires_in": SESSION_TTL_SECONDS}


def _ai_budget(db: DbSession) -> dict:
    from .ai import budget_state  # локально: ai импортирует модели, admin — лёгкий модуль
    return budget_state(db, _now())


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
        "ai_budget": _ai_budget(db),  # расходы ИИ и уровень бюджета: ok | warn (80%) | exhausted (100%)
    }


@router.get("/analytics")
def analytics_summary(days: int = 30, _: User = Depends(require_admin), db: DbSession = Depends(get_session)) -> dict:
    """3.9: счётчики событий за последние дни (без пользователей и адресов)."""

    from .analytics import summary

    days = max(1, min(days, 365))
    since = (_dt.now(_tz.utc) - _td(days=days)).strftime("%Y-%m-%d")
    return {"sinceDay": since, "rows": summary(db, since)}


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


@router.get("/ai-feedback")
def ai_feedback_list(_: User = Depends(require_admin), db: DbSession = Depends(get_session)) -> dict:
    """Жалобы («Пожаловаться») и 👎 на ответы помощника — для проверки качества на бете. Вопрос уже с маскировкой."""
    from .models import AIFeedback
    rows = db.scalars(select(AIFeedback).where(AIFeedback.kind.in_(("flag", "down")))
                      .order_by(AIFeedback.created_at.desc()).limit(200)).all()
    return {"items": [{
        "id": r.id,
        "created_at": _aware(r.created_at).isoformat(),
        "kind": r.kind,
        "reason": r.reason,
        "question": r.question_masked,
        "refused": r.refused,
        "refusal_category": r.refusal_category,
        "shop_id": r.shop_id,
    } for r in rows]}


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


# ---------- доступ к аккаунтам по номеру продавца (К-21, решения владельца 23.11.2026) ----------
# Каждое действие — только владелец, с подтверждением (confirm=true) и записью в audit_events: кто, что, до какой даты.

class ConfirmIn(BaseModel):
    confirm: bool = False


class SellerBlockIn(ConfirmIn):
    blocked: bool


class SpecialIn(ConfirmIn):
    months: int
    comment: str = ""


def _seller(db: DbSession, number: str):
    from .seller_access import SellerNumber

    row = db.get(SellerNumber, number.strip())
    if row is None:
        raise ApiError(404, "not_found", "Номер продавца не найден.")
    return row


def _confirmed(body: ConfirmIn) -> None:
    if not body.confirm:
        raise ApiError(422, "confirm_required", "Подтвердите действие.")


def _audit(db: DbSession, admin: User, action: str, entity: str, shop_id: str | None) -> None:
    from . import audit

    audit.record(db, action, entity, actor_id=admin.id, shop_id=shop_id)


def _seller_view(db: DbSession, row) -> dict:
    from . import billing
    from .models import KaspiConnection
    from .seller_access import SpecialAccess

    conn = db.get(KaspiConnection, row.shop_id) if row.shop_id else None
    shop = db.get(Shop, row.shop_id) if row.shop_id else None
    user = db.get(User, row.user_id) if row.user_id else None
    specials = db.scalars(select(SpecialAccess).where(SpecialAccess.number == row.number)
                          .order_by(SpecialAccess.created_at.desc())).all()
    sub = billing.subscription_view(db, shop) if shop is not None else None
    return {
        "number": row.number,
        "account": "deleted" if row.user_id is None else ("blocked" if row.blocked_at else "active"),
        "email": user.email if user else None,
        "shop_name": shop.name if shop else None,
        "seller_id": conn.seller_id if conn else None,  # ID продавца Kaspi; токен в админке не показывается
        "kaspi_status": conn.status if conn else None,
        "reconnect_until": _aware(conn.reconnect_until).isoformat() if conn and conn.reconnect_until else None,
        "subscription": sub,
        "special_access": [{"from": _aware(s.starts_at).isoformat(), "until": _aware(s.ends_at).isoformat(),
                            "cancelled_at": _aware(s.cancelled_at).isoformat() if s.cancelled_at else None,
                            "comment": s.comment} for s in specials],
    }


@router.get("/sellers/{number}")
def seller_get(number: str, _: User = Depends(require_admin), db: DbSession = Depends(get_session)) -> dict:
    """Поиск по номеру продавца: аккаунт, магазин, подписка, особые условия."""
    return _seller_view(db, _seller(db, number))


@router.post("/sellers/{number}/block")
def seller_block(number: str, body: SellerBlockIn, admin: User = Depends(require_admin),
                 db: DbSession = Depends(get_session)) -> dict:
    """Блокировка: продавец видит сообщение с контактом поддержки; удалить аккаунт может всегда (правила магазинов).
    Блокировка хранится на номере продавца и переживает удаление аккаунта."""
    _confirmed(body)
    row = _seller(db, number)
    now = _now()
    row.blocked_at = now if body.blocked else None
    user = db.get(User, row.user_id) if row.user_id else None
    if user is not None:
        user.blocked_at = now if body.blocked else None
    db.commit()
    _audit(db, admin, "seller_block" if body.blocked else "seller_unblock", f"seller:{row.number}", row.shop_id)
    return _seller_view(db, row)


@router.post("/sellers/{number}/reconnect")
def seller_reconnect(number: str, body: ConfirmIn, admin: User = Depends(require_admin),
                     db: DbSession = Depends(get_session)) -> dict:
    """«Возобновить доступ» к Kaspi: одноразовое окно на 24 часа, чтобы продавец ввёл новый токен того же магазина."""
    from .models import KaspiConnection
    from .seller_access import RECONNECT_HOURS

    _confirmed(body)
    row = _seller(db, number)
    conn = db.get(KaspiConnection, row.shop_id) if row.shop_id else None
    if conn is None:
        raise ApiError(409, "kaspi_not_connected", "У этого номера нет подключённого магазина Kaspi.")
    until = _now() + timedelta(hours=RECONNECT_HOURS)
    conn.reconnect_until = until
    db.commit()
    _audit(db, admin, "kaspi_reconnect_window", f"seller:{row.number}:{until.date().isoformat()}", row.shop_id)
    return _seller_view(db, row)


@router.post("/sellers/{number}/special-access")
def seller_special_grant(number: str, body: SpecialIn, admin: User = Depends(require_admin),
                         db: DbSession = Depends(get_session)) -> dict:
    """Доступ без подписки на 1, 3 или 6 месяцев. Только бесплатно (OPERATIONS.md: продавать в обход магазинов нельзя)."""
    from .seller_access import grant_special

    _confirmed(body)
    row = _seller(db, number)
    if row.user_id is None:
        raise ApiError(409, "account_deleted", "Аккаунт этого продавца удалён.")
    sa = grant_special(db, row.number, body.months, body.comment)
    db.commit()
    _audit(db, admin, "special_access_grant", f"seller:{row.number}:{_aware(sa.ends_at).date().isoformat()}",
           row.shop_id)
    return _seller_view(db, row)


@router.post("/sellers/{number}/special-access/cancel")
def seller_special_cancel(number: str, body: ConfirmIn, admin: User = Depends(require_admin),
                          db: DbSession = Depends(get_session)) -> dict:
    from .seller_access import cancel_special

    _confirmed(body)
    row = _seller(db, number)
    cancel_special(db, row.number)
    db.commit()
    _audit(db, admin, "special_access_cancel", f"seller:{row.number}", row.shop_id)
    return _seller_view(db, row)


@router.get("/special-access")
def special_access_list(_: User = Depends(require_admin), db: DbSession = Depends(get_session)) -> dict:
    """Вкладка «Особые условия»: магазин, ID продавца, с какого по какое число, комментарий владельца."""
    from .models import KaspiConnection
    from .seller_access import SellerNumber, SpecialAccess

    now = _now()
    items = []
    for sa in db.scalars(select(SpecialAccess).order_by(SpecialAccess.created_at.desc()).limit(500)).all():
        row = db.get(SellerNumber, sa.number)
        shop = db.get(Shop, row.shop_id) if row and row.shop_id else None
        conn = db.get(KaspiConnection, row.shop_id) if row and row.shop_id else None
        active = sa.cancelled_at is None and _aware(sa.starts_at) <= now < _aware(sa.ends_at)
        items.append({"number": sa.number, "shop_name": shop.name if shop else None,
                      "seller_id": conn.seller_id if conn else None,
                      "from": _aware(sa.starts_at).isoformat(), "until": _aware(sa.ends_at).isoformat(),
                      "cancelled_at": _aware(sa.cancelled_at).isoformat() if sa.cancelled_at else None,
                      "active": active, "comment": sa.comment})
    return {"items": items}


# ---------- разрешение пользователя на доступ поддержки (раздел 14.3) ----------

me_router = APIRouter(tags=["пользователь"])


@me_router.post("/me/support-access")
def grant_support_access(principal: Principal = Depends(get_principal), db: DbSession = Depends(get_session)) -> dict:
    """Пользователь разрешает поддержке посмотреть его магазины на 24 часа."""
    user = current_user(principal, db)
    until = _now() + timedelta(hours=SUPPORT_ACCESS_HOURS)
    user.support_access_until = until
    from . import analytics as analytics_service

    db.commit()
    analytics_service.record_safe("support_access_granted", _now())  # 3.9: после commit
    return {"access_until": until.isoformat()}


@me_router.delete("/me/support-access")
def revoke_support_access(principal: Principal = Depends(get_principal), db: DbSession = Depends(get_session)) -> dict:
    user = current_user(principal, db)
    user.support_access_until = None
    db.commit()
    return {"access_until": None}


__all__ = ["router", "me_router", "totp_code", "totp_verify"]
