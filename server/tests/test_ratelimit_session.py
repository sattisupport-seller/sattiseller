"""К-2 п.4 (риск 1.16): счётчик лимита ведётся в сессии запроса, второе соединение не открывается."""

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DbSession

from app import ratelimit
from app.db import SessionLocal, engine


def test_counter_uses_request_session_and_opens_no_second_connection(monkeypatch):
    # имитируем PostgreSQL-путь (на тестовой SQLite счётчик иначе ведётся в памяти процесса)
    monkeypatch.setattr(ratelimit, "_is_sqlite", lambda: False)

    def _no_second_session():
        raise AssertionError("allow() не должен открывать отдельное соединение, когда передана сессия запроса")

    monkeypatch.setattr(ratelimit, "SessionLocal", _no_second_session)
    key = "test-session-counter"
    with DbSession(engine) as db:
        assert ratelimit.allow(key, 2, 3600, db=db) is True
        assert ratelimit.allow(key, 2, 3600, db=db) is True
        assert ratelimit.allow(key, 2, 3600, db=db) is False  # лимит исчерпан
    with DbSession(engine) as db:  # счётчик сохранился между сессиями
        assert ratelimit.allow(key, 2, 3600, db=db) is False


def test_insert_conflict_in_request_session_falls_back_to_separate_session(monkeypatch):
    """Конфликт вставки в сессии запроса: откат и отдельная сессия, как раньше — лимит всё равно считается."""
    monkeypatch.setattr(ratelimit, "_is_sqlite", lambda: False)
    monkeypatch.setattr(ratelimit, "SessionLocal", SessionLocal)  # отдельная сессия работает на тестовой базе

    def _conflict(db, key, limit, window):
        raise IntegrityError("insert", {}, Exception("duplicate key"))

    monkeypatch.setattr(ratelimit, "_allow_in_session", _conflict)
    rolled = {"n": 0}

    with DbSession(engine) as db:
        real_rollback = db.rollback

        def _count_rollback():
            rolled["n"] += 1
            real_rollback()

        monkeypatch.setattr(db, "rollback", _count_rollback)
        assert ratelimit.allow("test-conflict-key-2", 5, 3600, db=db) is True
    assert rolled["n"] == 1
