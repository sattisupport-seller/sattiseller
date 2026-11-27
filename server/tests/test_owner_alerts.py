"""3.10: оповещения владельцу — пороги, однократная отправка, повтор после сбоя почты."""

import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy.orm import Session as DbSession

from app import owner_alerts
from app.db import engine
from app.mailer import MailError
from app.errorlog import AppError


@pytest.fixture
def sent(monkeypatch):
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(owner_alerts, "send_owner_alert", lambda subject, text: calls.append((subject, text)) or True)
    return calls


def _old_backup(path: Path, hours: int, now: datetime) -> None:
    path.mkdir(parents=True, exist_ok=True)
    f = path / "satti-20261120-000000-000000.bak"
    f.write_bytes(b"x")
    ts = (now - timedelta(hours=hours)).timestamp()
    os.utime(f, (ts, ts))


def test_backup_alert_when_missing_and_not_repeated(sent, tmp_path):
    now = datetime(2026, 11, 21, 12, 0, tzinfo=timezone.utc)
    with DbSession(engine) as db:
        assert owner_alerts.check_backup(db, now, tmp_path / "none") is True
        db.commit()
        assert owner_alerts.check_backup(db, now, tmp_path / "none") is False
    assert len(sent) == 1 and "резервная копия" in sent[0][0].lower()


def test_no_backup_alert_when_recent(sent, tmp_path):
    now = datetime(2026, 11, 21, 12, 0, tzinfo=timezone.utc)
    _old_backup(tmp_path, hours=2, now=now)
    with DbSession(engine) as db:
        assert owner_alerts.check_backup(db, now, tmp_path) is False
    assert sent == []


def test_backup_alert_when_older_than_26_hours(sent, tmp_path):
    now = datetime(2026, 11, 21, 12, 0, tzinfo=timezone.utc)
    _old_backup(tmp_path, hours=27, now=now)
    with DbSession(engine) as db:
        assert owner_alerts.check_backup(db, now, tmp_path) is True


def _error_group(first_seen: datetime) -> AppError:
    fp = uuid.uuid4().hex[:32]
    return AppError(fingerprint=fp, kind="server", exc_type="ValueError", where="x", message="m", count=1,
                    first_seen=first_seen, last_seen=first_seen)


def test_server_error_alert_needs_five_new_groups(sent):
    now = datetime(2026, 11, 21, 12, 0, tzinfo=timezone.utc)
    with DbSession(engine) as db:
        for _ in range(4):
            db.add(_error_group(now - timedelta(minutes=5)))
        db.commit()
        assert owner_alerts.check_server_errors(db, now) is False
        db.add(_error_group(now - timedelta(minutes=1)))
        db.commit()
        assert owner_alerts.check_server_errors(db, now) is True
        db.commit()
    assert len(sent) == 1


def test_kaspi_alert_only_on_mass_failure(sent):
    now = datetime(2026, 11, 21, 12, 0, tzinfo=timezone.utc)
    with DbSession(engine) as db:
        assert owner_alerts.check_kaspi_results(db, now, [("a", "synced"), ("b", "error")]) is False  # меньше трёх
        assert owner_alerts.check_kaspi_results(db, now, [("a", "synced"), ("b", "error"), ("c", "synced")]) is False
        assert owner_alerts.check_kaspi_results(db, now, [("a", "error"), ("b", "unavailable"), ("c", "synced")]) is True
    assert len(sent) == 1


def test_daily_summary_at_nine_almaty_once(sent):
    tz = ZoneInfo("Asia/Almaty")
    early = datetime(2026, 11, 21, 8, 30, tzinfo=tz).astimezone(timezone.utc)
    nine = datetime(2026, 11, 21, 9, 5, tzinfo=tz).astimezone(timezone.utc)
    with DbSession(engine) as db:
        assert owner_alerts.check_daily_summary(db, early) is False
        assert owner_alerts.check_daily_summary(db, nine) is True
        db.commit()
        assert owner_alerts.check_daily_summary(db, nine + timedelta(hours=2)) is False
    assert len(sent) == 1 and "Сводка" in sent[0][1]


def test_failed_mail_is_retried(monkeypatch, tmp_path):
    attempts = []

    def flaky(subject, text):
        attempts.append(subject)
        if len(attempts) == 1:
            raise MailError("почта недоступна")
        return True

    monkeypatch.setattr(owner_alerts, "send_owner_alert", flaky)
    now = datetime(2026, 11, 21, 12, 0, tzinfo=timezone.utc)
    with DbSession(engine) as db:
        assert owner_alerts.check_backup(db, now, tmp_path / "none") is False
        db.commit()
        assert owner_alerts.check_backup(db, now, tmp_path / "none") is True
        db.commit()
    assert len(attempts) == 2


def test_error_spike_counts_occurrences_in_window(sent, monkeypatch):
    from app.models import AppErrorEvent

    monkeypatch.setattr(owner_alerts, "SPIKE_MIN_EVENTS", 3)
    now = datetime(2026, 11, 21, 12, 0, tzinfo=timezone.utc)
    with DbSession(engine) as db:
        for _ in range(2):
            db.add(AppErrorEvent(fingerprint="fp1", created_at=now - timedelta(minutes=5)))
        db.add(AppErrorEvent(fingerprint="fp1", created_at=now - timedelta(hours=2)))  # вне окна
        db.commit()
        assert owner_alerts.check_error_spike(db, now) is False  # 2 в окне: мало
        db.add(AppErrorEvent(fingerprint="fp2", created_at=now - timedelta(minutes=1)))
        db.commit()
        assert owner_alerts.check_error_spike(db, now) is True  # 3 в окне
        db.commit()
        assert owner_alerts.check_error_spike(db, now) is False  # то же окно — повтора нет
    assert len(sent) == 1 and "всплеск" in sent[0][0].lower()


def test_error_events_older_than_two_days_are_purged():
    from app.models import AppErrorEvent

    now = datetime(2026, 11, 21, 12, 0, tzinfo=timezone.utc)
    with DbSession(engine) as db:
        db.add(AppErrorEvent(fingerprint="old", created_at=now - timedelta(days=3)))
        db.add(AppErrorEvent(fingerprint="new", created_at=now - timedelta(days=1)))
        db.commit()
        assert owner_alerts.purge_error_events(db, now) == 1
        db.commit()
        assert db.query(AppErrorEvent).count() == 1


def test_disk_alert_when_space_low_once_per_day(sent):
    """4.2: свободно меньше 10% или меньше 2 ГБ — письмо владельцу, не чаще раза в сутки."""
    now = datetime(2026, 11, 27, 6, 0, tzinfo=timezone.utc)
    gb = 1024 ** 3
    with DbSession(engine) as db:
        assert owner_alerts.check_disk(db, now, usage=(100 * gb, 50 * gb, 50 * gb)) is False
        assert owner_alerts.check_disk(db, now, usage=(100 * gb, 95 * gb, 5 * gb)) is True  # 5% свободно
        assert owner_alerts.check_disk(db, now + timedelta(hours=2), usage=(100 * gb, 95 * gb, 5 * gb)) is False
        assert owner_alerts.check_disk(db, now + timedelta(days=1), usage=(10 * gb, 8.5 * gb, 1.5 * gb)) is True  # < 2 ГБ
        db.rollback()
    assert "место" in sent[0][0]
