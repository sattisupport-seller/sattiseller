"""Планировщик хранения (ТЗ 2.1, 9.3): флаг выключен по умолчанию, запуск идемпотентен."""

from datetime import datetime, timezone

from app import scheduler


def test_builtin_scheduler_is_off_by_default(monkeypatch):
    monkeypatch.delenv("SATTI_SCHEDULER", raising=False)
    assert scheduler.start_builtin_scheduler() is None


def test_daily_job_runs_and_is_idempotent(client):
    now = datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc)
    first = scheduler.run_daily_jobs(now)
    second = scheduler.run_daily_jobs(now)
    assert first == [] and second == []
