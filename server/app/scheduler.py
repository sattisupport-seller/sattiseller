"""Планировщик ежедневных задач (ТЗ 2.1, 9.3): письма о хранении 0/60/83 день и удаление на 90-й день.

Встроенный: поток в процессе сервера раз в сутки, если задан SATTI_SCHEDULER=1 (в тестах выключен).
Разовый запуск: из папки server — `python -m app.scheduler` (удобно для внешнего cron, если понадобится).
Один запуск идемпотентен: письма и удаления не повторяются (таблица retention_events).
"""

from __future__ import annotations

import logging
import os
import threading
from datetime import datetime, timezone

from .billing import run_retention
from .db import SessionLocal

log = logging.getLogger("satti.scheduler")
INTERVAL_SECONDS = 24 * 3600


def run_daily_jobs(now: datetime | None = None) -> list[tuple[str, str]]:
    """Одна итерация: возвращает пары (магазин, действие), которые сделаны."""
    now = now or datetime.now(timezone.utc)
    db = SessionLocal()
    try:
        done = run_retention(db, now)
    finally:
        db.close()
    # в журнал — только идентификаторы магазинов и действия, без адресов и данных покупателей
    log.info("retention: %d действий", len(done))
    return done


_stop = threading.Event()


def _loop() -> None:
    while not _stop.is_set():
        try:
            run_daily_jobs()
        except Exception:  # noqa: BLE001 — задача не должна валить сервер; ошибку увидим в журнале
            log.exception("daily job failed")
        _stop.wait(INTERVAL_SECONDS)


def run_kaspi_sync(now: datetime | None = None) -> list[tuple[str, str]]:
    """Синхронизация заказов Kaspi для подключений, где пора (раз в 15 минут; 2.2). Без записи ключей в журнал."""
    from .kaspi import sync_due

    now = now or datetime.now(timezone.utc)
    db = SessionLocal()
    try:
        done = sync_due(db, now)
    finally:
        db.close()
    log.info("kaspi: %d синхронизаций", len(done))
    return done


def _kaspi_loop() -> None:
    from .kaspi import SYNC_EVERY

    while not _stop.is_set():
        try:
            run_kaspi_sync()
        except Exception:  # noqa: BLE001 — задача не должна валить сервер
            log.exception("kaspi sync loop failed")
        _stop.wait(SYNC_EVERY)


def start_builtin_scheduler() -> threading.Thread | None:
    """Запускает поток, если SATTI_SCHEDULER=1. Возвращает поток или None."""
    if os.environ.get("SATTI_SCHEDULER", "0") != "1":
        return None
    thread = threading.Thread(target=_loop, name="satti-daily-jobs", daemon=True)
    thread.start()
    from .config import settings

    if settings.kaspi_connection_enabled:
        threading.Thread(target=_kaspi_loop, name="satti-kaspi-sync", daemon=True).start()
    return thread


def stop_builtin_scheduler() -> None:
    _stop.set()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    result = run_daily_jobs()
    print(f"готово: {len(result)} действий")
