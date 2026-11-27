"""Планировщик ежедневных задач (ТЗ 2.1, 9.3): письма о хранении 0/60/83 день и удаление на 90-й день.

Встроенный: поток в процессе сервера раз в сутки, если задан SATTI_SCHEDULER=1 (в тестах выключен).
Разовый запуск: из папки server — `python -m app.scheduler` (удобно для внешнего cron, если понадобится).
Один запуск идемпотентен: письма и удаления не повторяются (таблица retention_events).
"""

from __future__ import annotations
from sqlalchemy import delete, select
from datetime import timedelta

import logging
import os
import threading
from datetime import datetime, timezone

from .billing import run_retention
from .db import SessionLocal

log = logging.getLogger("satti.scheduler")
INTERVAL_SECONDS = 24 * 3600


AI_FEEDBACK_KEEP_DAYS = 365  # оценки и жалобы на ответы помощника — 12 месяцев (решение владельца 22.11)


def purge_old_ai_feedback(db, now: datetime) -> int:
    """Удаляет оценки и жалобы старше 12 месяцев. Возвращает число удалённых."""
    from .models import AIFeedback
    cut = now - timedelta(days=AI_FEEDBACK_KEEP_DAYS)
    res = db.execute(delete(AIFeedback).where(AIFeedback.created_at < cut))
    db.commit()
    return res.rowcount or 0


def run_daily_jobs(now: datetime | None = None) -> list[tuple[str, str]]:
    """Одна итерация: возвращает пары (магазин, действие), которые сделаны."""
    now = now or datetime.now(timezone.utc)
    db = SessionLocal()
    try:
        from .accounts import purge_deactivated

        purge_old_ai_feedback(db, now)
        purged = purge_deactivated(db, now)  # К-21: 30 дней деактивации прошли — полное удаление
        from .ratelimit import purge_expired

        purge_expired()  # аудит 27.11, L2: старые счётчики лимитов не копятся
        done = run_retention(db, now)
        done += [("-", "deactivated_purged")] * purged
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

    from .owner_alerts import check_kaspi_results

    now = now or datetime.now(timezone.utc)
    db = SessionLocal()
    try:
        done = sync_due(db, now)
        check_kaspi_results(db, now, done)  # 3.10: массовые ошибки синхронизации — письмо владельцу
        db.commit()
    finally:
        db.close()
    log.info("kaspi: %d синхронизаций", len(done))
    return done


def run_kaspi_nightly_reread(now: datetime | None = None) -> list[tuple[str, str]]:
    """К-17.2: раз в сутки (ночью по Алматы) перечитываем заказы Kaspi за 60 дней вместе с составом."""
    from .kaspi import client_for, refresh_open_orders
    from .kaspi_client import KaspiAuthError, KaspiUnavailable
    from .models import KaspiConnection

    now = now or datetime.now(timezone.utc)
    db = SessionLocal()
    done: list[tuple[str, str]] = []
    try:
        from .accounts import deactivated_shop_ids

        paused = deactivated_shop_ids(db)  # К-21: деактивированные аккаунты не перечитываются
        conns = db.scalars(select(KaspiConnection).where(KaspiConnection.status == "active")).all()
        for conn in conns:
            if conn.shop_id in paused:
                continue
            client = None
            try:
                client = client_for(conn)
                refresh_open_orders(db, conn, client, now)
                done.append((conn.shop_id, "refreshed"))
            except KaspiAuthError:
                done.append((conn.shop_id, "token_invalid"))
            except KaspiUnavailable:
                done.append((conn.shop_id, "unavailable"))
            except Exception:  # noqa: BLE001 — один магазин не останавливает остальные
                log.exception("kaspi nightly reread failed for shop %s", conn.shop_id)
                db.rollback()
                done.append((conn.shop_id, "error"))
            finally:
                if client is not None:
                    client.close()
    finally:
        db.close()
    log.info("kaspi nightly: %d магазинов", len(done))
    return done


NIGHTLY_HOUR = 3  # ночное перечитывание заказов Kaspi — с 03:00 по Алматы


def nightly_due(now_utc: datetime, last_day) -> bool:
    """Пора ли ночное перечитывание: после 03:00 по Алматы и ещё не было сегодня (К-30, D1: раньше поток падал
    на импорте несуществующей константы и в бою не запускался ни разу)."""
    from zoneinfo import ZoneInfo

    local = now_utc.astimezone(ZoneInfo("Asia/Almaty"))
    return local.hour >= NIGHTLY_HOUR and last_day != local.date()


def _kaspi_nightly_loop() -> None:
    """Проверка раз в час; задача запускается один раз в сутки в 03:00 по Алматы (UTC+5)."""
    from zoneinfo import ZoneInfo

    tz = ZoneInfo("Asia/Almaty")
    last_day = None
    while not _stop.is_set():
        now = datetime.now(timezone.utc)
        local = now.astimezone(tz)
        if nightly_due(now, last_day):
            try:
                run_kaspi_nightly_reread()
                last_day = local.date()
            except Exception:  # noqa: BLE001 — задача не должна валить сервер
                log.exception("kaspi nightly loop failed")
        _stop.wait(3600)


def run_owner_checks_once(now: datetime | None = None) -> list[str]:
    """3.10: проверки для владельца (резервная копия, ошибки сервера, сводка за день). Раз в час."""
    from .owner_alerts import run_owner_checks

    now = now or datetime.now(timezone.utc)
    db = SessionLocal()
    try:
        return run_owner_checks(db, now)
    finally:
        db.close()


def _owner_loop() -> None:
    while not _stop.is_set():
        try:
            run_owner_checks_once()
        except Exception:  # noqa: BLE001 — задача не должна валить сервер
            log.exception("owner checks failed")
        _stop.wait(3600)


def _kaspi_loop() -> None:
    from .kaspi import SYNC_EVERY

    while not _stop.is_set():
        try:
            run_kaspi_sync()
        except Exception:  # noqa: BLE001 — задача не должна валить сервер
            log.exception("kaspi sync loop failed")
        _stop.wait(SYNC_EVERY)


def run_push_once(now: datetime | None = None) -> int:
    """3.4: сводка по понедельникам (сама проверяет час) и отправка созревших уведомлений."""
    from .push import dispatch_due, weekly_summary_due

    now = now or datetime.now(timezone.utc)
    db = SessionLocal()
    try:
        weekly_summary_due(db, now)
        return dispatch_due(db, now)
    finally:
        db.close()


def _push_loop() -> None:
    while not _stop.is_set():
        try:
            run_push_once()
        except Exception:  # noqa: BLE001 — задача не должна валить сервер
            log.exception("push loop failed")
        _stop.wait(300)


def start_builtin_scheduler() -> threading.Thread | None:
    """Запускает поток, если SATTI_SCHEDULER=1. Возвращает поток или None."""
    if os.environ.get("SATTI_SCHEDULER", "0") != "1":
        return None
    thread = threading.Thread(target=_loop, name="satti-daily-jobs", daemon=True)
    thread.start()
    from .config import settings

    if settings.kaspi_connection_enabled:
        threading.Thread(target=_kaspi_loop, name="satti-kaspi-sync", daemon=True).start()
        threading.Thread(target=_kaspi_nightly_loop, name="satti-kaspi-nightly", daemon=True).start()
    threading.Thread(target=_owner_loop, name="satti-owner-checks", daemon=True).start()
    threading.Thread(target=_push_loop, name="satti-push", daemon=True).start()  # 3.4
    return thread


def stop_builtin_scheduler() -> None:
    _stop.set()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    result = run_daily_jobs()
    print(f"готово: {len(result)} действий")
