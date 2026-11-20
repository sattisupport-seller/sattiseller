"""Ограничение частоты (ADR-0005, пункт 1.15): счётчики общие для всех процессов — в базе данных.

Один ключ — одна строка: начало окна и число попаданий. Строка блокируется на время проверки
(PostgreSQL: SELECT ... FOR UPDATE), поэтому два процесса не пройдут лимит одновременно.
Окно — фиксированное, начинается с первого попадания после истечения предыдущего.
"""

import os
import time
from collections import defaultdict, deque
from datetime import datetime, timezone

from fastapi import Request
from sqlalchemy import DateTime, Integer, String
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base, SessionLocal, engine

WINDOW_SECONDS = 3600


class RateLimit(Base):
    __tablename__ = "rate_limits"
    key: Mapped[str] = mapped_column(String(160), primary_key=True)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    count: Mapped[int] = mapped_column(Integer, default=0)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


_hits: dict[str, deque[float]] = defaultdict(deque)  # память процесса: только для SQLite (разработка, тесты)


def _memory_allow(key: str, limit: int, window: int) -> bool:
    now = time.monotonic()
    q = _hits[key]
    while q and now - q[0] > window:
        q.popleft()
    if len(q) >= limit:
        return False
    q.append(now)
    return True


def _is_sqlite() -> bool:
    return engine.dialect.name == "sqlite"


def allow(key: str, limit: int, window: int = WINDOW_SECONDS) -> bool:
    """True — попадание засчитано; False — лимит исчерпан (счётчик не растёт).

    PostgreSQL: счётчик в таблице rate_limits — общий для всех процессов (ADR-0005).
    SQLite: счётчик в памяти процесса (одна база на один процесс; общая запись по SQLite ломает транзакции запроса).
    """
    if _is_sqlite():
        return _memory_allow(key, limit, window)
    for attempt in range(2):  # второй заход — если две вставки нового ключа столкнулись
        now = datetime.now(timezone.utc)
        db = SessionLocal()
        try:
            row = db.get(RateLimit, key, with_for_update=True)
            if row is None:
                row = RateLimit(key=key, window_start=now, count=0)
                db.add(row)
            elif (now - _aware(row.window_start)).total_seconds() >= window:
                row.window_start = now
                row.count = 0
            if row.count >= limit:
                db.commit()
                return False
            row.count += 1
            db.commit()
            return True
        except IntegrityError:
            db.rollback()
            if attempt == 1:
                raise
        finally:
            db.close()
    return False


def reset() -> None:
    """Для тестов: сбрасывает все счётчики."""
    _hits.clear()
    if _is_sqlite():
        return
    db = SessionLocal()
    try:
        db.query(RateLimit).delete()
        db.commit()
    finally:
        db.close()


def _trusted_proxies() -> frozenset[str]:
    raw = os.environ.get("SATTI_TRUSTED_PROXIES", "")
    return frozenset(p.strip() for p in raw.split(",") if p.strip())


def client_ip(request: Request) -> str:
    """Адрес клиента для лимитов (AUD-14).

    За обратным прокси все запросы приходят с адреса прокси, и лимит стал бы общим для всех.
    Заголовки X-Forwarded-For / X-Real-IP учитываются только если непосредственный адрес — доверенный прокси
    (SATTI_TRUSTED_PROXIES). Иначе клиент мог бы подделать адрес и обойти лимит.
    """
    peer = request.client.host if request.client else "unknown"
    trusted = _trusted_proxies()
    if peer not in trusted:
        return peer
    forwarded = [h.strip() for h in request.headers.get("x-forwarded-for", "").split(",") if h.strip()]
    for hop in reversed(forwarded):  # справа налево: первый адрес, который не наш прокси
        if hop not in trusted:
            return hop
    real = request.headers.get("x-real-ip", "").strip()
    return real or peer
