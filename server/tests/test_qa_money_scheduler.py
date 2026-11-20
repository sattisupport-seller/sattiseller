"""QA: добор покрытия критичных модулей — округления в тенге и ежедневные задачи хранения."""

import os
from datetime import datetime, timezone

import pytest

from app import scheduler
from app.money import apply_bp, format_tenge, parse_tenge_to_minor, round_half_up_div


def test_parse_rejects_garbage_amount():
    with pytest.raises(ValueError):
        parse_tenge_to_minor("сто тенге")


def test_parse_rejects_fraction_of_tiyn():
    with pytest.raises(ValueError):
        parse_tenge_to_minor("10.001")


def test_parse_accepts_exact_tiyn():
    assert parse_tenge_to_minor("1234.56") == 123456


def test_division_by_zero_is_refused():
    with pytest.raises(ValueError):
        round_half_up_div(5, 0)


def test_negative_rate_is_refused():
    with pytest.raises(ValueError):
        apply_bp(1000, -1)


def test_half_rounds_away_from_zero_for_negatives():
    assert round_half_up_div(-5, 2) == -3
    assert round_half_up_div(5, -2) == -3


def test_format_negative_uses_unicode_minus():
    assert format_tenge(-123456).replace(" ", " ") == "−1 235 ₸"  # -1234,56 round to -1 235


def test_run_daily_jobs_returns_list_and_does_not_fail_on_empty_db(monkeypatch):
    done = scheduler.run_daily_jobs(datetime(2026, 11, 20, tzinfo=timezone.utc))
    assert isinstance(done, list)


def test_builtin_scheduler_is_off_by_default(monkeypatch):
    monkeypatch.delenv("SATTI_SCHEDULER", raising=False)
    assert scheduler.start_builtin_scheduler() is None


def test_builtin_scheduler_starts_and_stops_when_enabled(monkeypatch):
    monkeypatch.setenv("SATTI_SCHEDULER", "1")
    monkeypatch.setattr(scheduler, "run_daily_jobs", lambda now=None: [])
    scheduler._stop.clear()  # другие тесты (выход из lifespan) оставляют событие установленным
    thread = scheduler.start_builtin_scheduler()
    try:
        assert thread is not None and thread.is_alive()
    finally:
        scheduler.stop_builtin_scheduler()
        thread.join(timeout=5)
        assert not thread.is_alive()
        scheduler._stop.clear()


def test_scheduler_loop_survives_a_failing_job(monkeypatch):
    calls = {"n": 0}

    def boom(now=None):
        calls["n"] += 1
        raise RuntimeError("сбой задачи")

    monkeypatch.setattr(scheduler, "run_daily_jobs", boom)
    scheduler._stop.clear()

    def stop_after_first_wait(timeout=None):
        scheduler._stop.set()
        return True

    monkeypatch.setattr(scheduler._stop, "wait", stop_after_first_wait)
    scheduler._loop()  # исключение внутри задачи не должно вывалиться наружу
    assert calls["n"] == 1
    scheduler._stop.clear()
