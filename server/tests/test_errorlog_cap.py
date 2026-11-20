"""AUD-18: число групп ошибок ограничено; сверх предела — одна общая группа."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from app import errorlog
from app.db import engine
from app.errorlog import AppError


def test_error_groups_are_capped(client, monkeypatch):
    monkeypatch.setattr(errorlog, "MAX_GROUPS", 3)
    for i in range(10):
        r = client.post("/v1/telemetry/errors",
                        json={"where": f"screen-{i}", "message": "boom", "exc_type": f"E{i}"})
        assert r.status_code == 202
    with DbSession(engine) as db:
        groups = db.scalar(select(func.count()).select_from(AppError))
        overflow = db.get(AppError, errorlog.OVERFLOW_FP)
        assert groups == 4  # три обычные группы и одна общая
        assert overflow is not None and overflow.count == 7
