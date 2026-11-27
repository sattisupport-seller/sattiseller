"""События использования (этап 3, задача 3.9; ТЗ 14.5).

Считаются только по дням и по имени события. Не сохраняются ни пользователь, ни устройство, ни адрес, ни сумма,
ни название товара. Список событий фиксирован: неизвестное имя отклоняется.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DbSession

from .models import AnalyticsDaily

ALLOWED_EVENTS = frozenset({
    "auth_method_used", "paywall_shown", "trial_started",
    "subscription_started", "subscription_renewed", "subscription_expired", "restore_tapped", "lock_screen_shown",
    "data_export_requested", "excel_exported", "tax_rate_saved", "notification_opened", "kaspi_connect_started",
    "kaspi_connect_succeeded", "kaspi_connect_failed", "support_access_granted",
})


class UnknownEvent(ValueError):
    pass


def record(db: DbSession, event: str, now: datetime) -> None:
    """Прибавляет 1 к счётчику события за день (UTC). Атомарно: обновление, а при отсутствии строки — вставка."""
    if event not in ALLOWED_EVENTS:
        raise UnknownEvent(event)
    utc = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
    day = utc.astimezone(timezone.utc).strftime("%Y-%m-%d")
    for attempt in range(2):
        updated = db.execute(update(AnalyticsDaily).where(AnalyticsDaily.day == day, AnalyticsDaily.event == event)
                             .values(count=AnalyticsDaily.count + 1)).rowcount
        if updated:
            db.commit()
            return
        try:
            db.add(AnalyticsDaily(day=day, event=event, count=1))
            db.commit()
            return
        except IntegrityError:
            # другая транзакция вставила строку раньше: во второй попытке — обновление
            db.rollback()
    raise RuntimeError("analytics counter not updated")


def record_safe(event: str, now: datetime) -> None:
    """Счётчик в отдельной сессии: не фиксирует и не откатывает транзакцию вызывающего кода; сбой счётчика
    не ломает основное действие (3.9)."""
    import logging

    from .db import SessionLocal

    try:
        with SessionLocal() as own:
            record(own, event, now)
    except Exception:  # noqa: BLE001 — аналитика второстепенна
        logging.getLogger("satti.analytics").warning("analytics event %s not recorded", event)


def summary(db: DbSession, since_day: str) -> list[dict]:
    rows = db.scalars(select(AnalyticsDaily).where(AnalyticsDaily.day >= since_day)
                      .order_by(AnalyticsDaily.day.desc(), AnalyticsDaily.event)).all()
    return [{"day": r.day, "event": r.event, "count": r.count} for r in rows]
