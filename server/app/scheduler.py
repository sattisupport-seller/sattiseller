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


def start_builtin_scheduler() -> threading.Thread | None:
    """Запускает поток, если SATTI_SCHEDULER=1. Возвращает поток или None."""
    if os.environ.get("SATTI_SCHEDULER", "0") != "1":
        return None
    thread = threading.Thread(target=_loop, name="satti-daily-jobs", daemon=True)
    thread.start()
    return thread


def stop_builtin_scheduler() -> None:
    _stop.set()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    result = run_daily_jobs()
    print(f"готово: {len(result)} действий")
