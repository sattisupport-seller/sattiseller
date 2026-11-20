"""Сбор ошибок своими силами (ТЗ 2.1, 14.4): таблица ошибок на сервере и просмотр в админ-панели.

Внешних сервисов нет. Что сохраняем: тип ошибки, место (маршрут или экран), текст без персональных данных
(маскировка privacy.mask_text, до 300 символов), версию и платформу приложения, счётчик и даты.
Не сохраняем: токены, тела запросов, ответы, идентификаторы пользователей и магазинов, стеки с данными.
Ошибки группируются по отпечатку (тип + место), чтобы одна проблема была одной строкой.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import DateTime, Integer, String, func, select
from sqlalchemy.orm import Mapped, Session as DbSession, mapped_column

from .admin import require_admin
from .db import Base, get_session
from .models import User
from .privacy import mask_text
from .ratelimit import allow, client_ip

log = logging.getLogger("satti.errors")
MAX_MESSAGE = 300


def _now() -> datetime:
    return datetime.now(timezone.utc)


class AppError(Base):
    __tablename__ = "app_errors"
    fingerprint: Mapped[str] = mapped_column(String(64), primary_key=True)
    kind: Mapped[str] = mapped_column(String(16))  # server | client
    exc_type: Mapped[str] = mapped_column(String(120))
    where: Mapped[str] = mapped_column(String(160))
    message: Mapped[str] = mapped_column(String(MAX_MESSAGE))
    app_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    platform: Mapped[str | None] = mapped_column(String(16), nullable=True)
    count: Mapped[int] = mapped_column(Integer, default=0)
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


def fingerprint(kind: str, exc_type: str, where: str) -> str:
    return hashlib.sha256(f"{kind}|{exc_type}|{where}".encode("utf-8")).hexdigest()[:32]


MAX_GROUPS = 500  # AUD-18: предел числа групп; сверх него все новые ошибки идут в одну общую группу
OVERFLOW_FP = "overflow"


def record_error(db: DbSession, *, kind: str, exc_type: str, where: str, message: str,
                 app_version: str | None = None, platform: str | None = None) -> str:
    """Сохраняет или обновляет группу ошибок. Возвращает идентификатор группы (отпечаток)."""
    exc_type, where = exc_type[:120], where[:160]
    fp = fingerprint(kind, exc_type, where)
    safe_message = mask_text(message or "")[:MAX_MESSAGE]
    now = _now()
    row = db.get(AppError, fp)
    if row is None and (db.scalar(select(func.count()).select_from(AppError)) or 0) >= MAX_GROUPS:
        fp, exc_type, where = OVERFLOW_FP, "overflow", "overflow"
        row = db.get(AppError, fp)
    if row is None:
        row = AppError(fingerprint=fp, kind=kind, exc_type=exc_type, where=where, message=safe_message,
                       app_version=(app_version or None) and app_version[:32], platform=(platform or None) and platform[:16],
                       count=0, first_seen=now, last_seen=now)
        db.add(row)
    row.count += 1
    row.last_seen = now
    row.message = safe_message
    db.commit()
    return fp


router = APIRouter(tags=["ошибки"])


class ClientErrorIn(BaseModel):
    where: str = Field(min_length=1, max_length=160)
    message: str = Field(default="", max_length=2000)
    exc_type: str = Field(default="ClientError", max_length=120)
    app_version: str | None = Field(default=None, max_length=32)
    platform: str | None = Field(default=None, max_length=16)


@router.post("/telemetry/errors", status_code=202)
def client_error(body: ClientErrorIn, request: Request, db: DbSession = Depends(get_session)) -> dict:
    """Ошибка из приложения. Анонимно, с лимитом на адрес: 60 в час."""
    ip = client_ip(request)
    if not allow(f"errors:{ip}", 60):
        return {"status": "throttled"}
    record_error(db, kind="client", exc_type=body.exc_type, where=body.where, message=body.message,
                 app_version=body.app_version, platform=body.platform)
    return {"status": "recorded"}


admin_router = APIRouter(prefix="/admin", tags=["админ"])


@admin_router.get("/errors")
def admin_errors(_: User = Depends(require_admin), db: DbSession = Depends(get_session)) -> dict:
    rows = db.scalars(select(AppError).order_by(AppError.last_seen.desc()).limit(200)).all()
    return {"items": [{
        "fingerprint": r.fingerprint, "kind": r.kind, "exc_type": r.exc_type, "where": r.where,
        "message": r.message, "app_version": r.app_version, "platform": r.platform, "count": r.count,
        "first_seen": r.first_seen.isoformat(), "last_seen": r.last_seen.isoformat(),
    } for r in rows]}


def unhandled_error_response(request: Request, exc: Exception, db: DbSession) -> JSONResponse:
    """Общий обработчик внутренних ошибок: пользователь видит код, в журнале — группа без данных."""
    error_id = uuid.uuid4().hex[:12]
    where = f"{request.method} {request.url.path.split('?')[0]}"
    try:
        record_error(db, kind="server", exc_type=type(exc).__name__, where=where, message=str(exc))
    except Exception:  # noqa: BLE001 — запись ошибки не должна мешать ответу
        log.exception("could not record error")
    log.error("unhandled %s at %s (id %s)", type(exc).__name__, where, error_id)
    return JSONResponse(status_code=500, content={"error": {
        "code": "internal", "message": "Внутренняя ошибка. Попробуйте ещё раз.", "error_id": error_id}})
