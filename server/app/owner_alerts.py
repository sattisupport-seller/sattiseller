"""Оповещения владельцу по email (этап 3, задача 3.10; ТЗ 29). WhatsApp — только после решения владельца.

Правила:
- резервная копия не сделана за последние 26 часов (папка SATTI_BACKUP_DIR, файлы satti-*.bak);
- новые группы ошибок сервера за 30 минут (≥ 5);
- всплеск: появлений ошибок сервера за 30 минут (≥ SATTI_ERROR_SPIKE_PER_30MIN, по умолчанию 50), по журналу появлений;
- массовые ошибки синхронизации Kaspi (≥ 3 подключения и не меньше половины с ошибкой в одном проходе);
- сводка за день в 09:00 по Алматы: новые пользователи и магазины, расход ИИ, отметки «не понравилось» за сутки.
Не реализовано: «сервер не отвечает» — нужен внешний сторож; ТЗ описывает его отдельно.
Каждое письмо уходит один раз на ключ (день, час или окно), отметка пишется после успешной отправки.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from .mailer import MailError, send_owner_alert
from .errorlog import AppError
from .models import AIFeedback, AIUsageEvent, AppErrorEvent, KaspiConnection, OwnerAlertLog, Shop, User

log = logging.getLogger("satti.owner")

BACKUP_MAX_AGE = timedelta(hours=26)
SERVER_ERROR_WINDOW = timedelta(minutes=30)
SERVER_ERROR_MIN_GROUPS = 5
SPIKE_WINDOW = timedelta(minutes=30)
SPIKE_MIN_EVENTS = int(os.environ.get("SATTI_ERROR_SPIKE_PER_30MIN", "50"))  # всплеск: появлений ошибок за 30 минут
KASPI_MIN_CONNECTIONS = 3
SUMMARY_TZ = ZoneInfo("Asia/Almaty")
SUMMARY_HOUR = 9


def _sent_once(db: DbSession, key: str) -> bool:
    return db.get(OwnerAlertLog, key) is not None


def _send(db: DbSession, key: str, subject: str, text: str, now: datetime) -> bool:
    if _sent_once(db, key):
        return False
    try:
        delivered = send_owner_alert(subject, text)
    except MailError:
        log.error("owner alert %s not sent: mail unavailable", key)
        return False
    if delivered:
        db.add(OwnerAlertLog(key=key, sent_at=now))
        db.flush()
    return delivered


def latest_backup_time(backup_dir: Path) -> datetime | None:
    files = list(backup_dir.glob("satti-*.bak")) if backup_dir.exists() else []
    if not files:
        return None
    return datetime.fromtimestamp(max(f.stat().st_mtime for f in files), timezone.utc)


def check_backup(db: DbSession, now: datetime, backup_dir: Path) -> bool:
    last = latest_backup_time(backup_dir)
    if last is not None and now - last <= BACKUP_MAX_AGE:
        return False
    when = last.isoformat() if last else "копий нет"
    return _send(db, f"backup:{now:%Y-%m-%d}", "Satti: резервная копия не сделана",
                 f"Последняя резервная копия: {when}. Проверьте расписание scripts/backup.py (docs/OPERATIONS.md).", now)


def check_server_errors(db: DbSession, now: datetime) -> bool:
    since = now - SERVER_ERROR_WINDOW
    new_groups = db.scalar(select(func.count()).select_from(AppError).where(
        AppError.kind == "server", AppError.first_seen >= since)) or 0
    if new_groups < SERVER_ERROR_MIN_GROUPS:
        return False
    return _send(db, f"errors:{now:%Y-%m-%d-%H}:{now.minute // 30}", "Satti: новые ошибки сервера",
                 f"За последние 30 минут появилось новых групп ошибок сервера: {new_groups}. "
                 "Подробности — в журнале ошибок админ-панели (без персональных данных).", now)


def check_error_spike(db: DbSession, now: datetime) -> bool:
    """Всплеск по числу появлений ошибок за 30 минут (3.10): считается по журналу появлений, не по группам."""
    since = now - SPIKE_WINDOW
    events = db.scalar(select(func.count()).select_from(AppErrorEvent).where(AppErrorEvent.created_at >= since)) or 0
    if events < SPIKE_MIN_EVENTS:
        return False
    return _send(db, f"spike:{now:%Y-%m-%d-%H}:{now.minute // 30}", "Satti: всплеск ошибок сервера",
                 f"За последние 30 минут сервер зафиксировал {events} ошибок. "
                 "Проверьте журнал ошибок в админ-панели (без персональных данных) и доступность сервера.", now)


def purge_error_events(db: DbSession, now: datetime) -> int:
    """Журнал появлений хранится двое суток."""
    removed = db.query(AppErrorEvent).filter(AppErrorEvent.created_at < now - timedelta(days=2)).delete()
    db.flush()
    return removed


def check_kaspi_results(db: DbSession, now: datetime, results: list[tuple[str, str]]) -> bool:
    if len(results) < KASPI_MIN_CONNECTIONS:
        return False
    failed = [r for r in results if r[1] != "synced"]
    if len(failed) * 2 < len(results):
        return False
    return _send(db, f"kaspi:{now:%Y-%m-%d-%H}", "Satti: массовые ошибки синхронизации Kaspi",
                 f"В последнем проходе синхронизации не удалось: {len(failed)} из {len(results)} магазинов. "
                 "Возможно, Kaspi недоступен или ключи отозваны. Список магазинов — в журнале сервера.", now)


def daily_summary_text(db: DbSession, now: datetime) -> str:
    since = now - timedelta(hours=24)
    users = db.scalar(select(func.count()).select_from(User).where(User.created_at >= since)) or 0
    shops = db.scalar(select(func.count()).select_from(Shop).where(Shop.is_demo.is_(False),
                                                                   Shop.created_at >= since)) or 0
    kaspi = db.scalar(select(func.count()).select_from(KaspiConnection)) or 0
    ai_micro = db.scalar(select(func.coalesce(func.sum(AIUsageEvent.cost_micro_usd), 0))
                         .where(AIUsageEvent.created_at >= since)) or 0
    down = db.scalar(select(func.count()).select_from(AIFeedback).where(
        AIFeedback.kind == "down", AIFeedback.created_at >= since)) or 0
    return (f"Сводка Satti за последние 24 часа.\n"
            f"Новых пользователей: {users}\n"
            f"Новых магазинов: {shops}\n"
            f"Подключений Kaspi всего: {kaspi}\n"
            f"Расход помощника ИИ: {ai_micro / 1_000_000:.2f} USD\n"
            f"Отметок «не понравилось» у помощника: {down}\n")


def check_daily_summary(db: DbSession, now: datetime) -> bool:
    local = now.astimezone(SUMMARY_TZ)
    if local.hour < SUMMARY_HOUR:
        return False
    return _send(db, f"summary:{local:%Y-%m-%d}", "Satti: сводка за день", daily_summary_text(db, now), now)


def run_owner_checks(db: DbSession, now: datetime, backup_dir: Path | None = None) -> list[str]:
    """Проверки для почасового запуска. Возвращает ключи отправленных оповещений."""
    backup_dir = backup_dir or Path(os.environ.get("SATTI_BACKUP_DIR", "./backups"))
    sent = []
    purge_error_events(db, now)
    for name, check in (("backup", lambda: check_backup(db, now, backup_dir)),
                        ("errors", lambda: check_server_errors(db, now)),
                        ("spike", lambda: check_error_spike(db, now)),
                        ("summary", lambda: check_daily_summary(db, now))):
        if check():
            sent.append(name)
    db.commit()
    return sent
