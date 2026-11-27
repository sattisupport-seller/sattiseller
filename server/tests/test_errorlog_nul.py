"""Фаззинг на PostgreSQL (27.11): нулевой байт в тексте ошибки давал 500 — PostgreSQL не хранит \x00 в тексте."""

from sqlalchemy.orm import Session as DbSession

from app.db import engine
from app.errorlog import AppError


def test_nul_bytes_are_stripped_from_client_error(client):
    r = client.post("/v1/telemetry/errors", json={"where": "screen\x00a", "message": "boom\x00", "exc_type": "E\x00",
                                                  "app_version": "1\x00", "platform": "ios\x00"})
    assert r.status_code == 202
    with DbSession(engine) as db:
        rows = [e for e in db.query(AppError).all() if e.where == "screena"]
    assert rows and rows[0].exc_type == "E" and "\x00" not in rows[0].message and rows[0].platform == "ios"
