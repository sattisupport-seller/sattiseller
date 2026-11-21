"""Вспомогательные функции SQL для копирования демо-шаблона (1.16).

На PostgreSQL копирование использует встроенные функции (md5, make_interval).
SQLite их не умеет, поэтому на каждом соединении регистрируются эти же функции на Python.
Результаты обеих баз совпадают: идентификатор строки — md5(исходный_id || магазин), сдвиг дат — в днях.
"""

from __future__ import annotations

import hashlib
from datetime import date, datetime, timedelta

_TS_FORMAT = "%Y-%m-%d %H:%M:%S.%f"  # формат, в котором SQLAlchemy хранит DateTime в SQLite


def newid(source_id: str, shop_id: str) -> str:
    return hashlib.md5(f"{source_id}{shop_id}".encode()).hexdigest()  # noqa: S324 — не для безопасности, для уникального id


def shift_timestamp(value: str | None, days: int) -> str | None:
    if value is None:
        return None
    moved = datetime.fromisoformat(value) + timedelta(days=days)
    return moved.strftime(_TS_FORMAT)


def shift_date(value: str | None, days: int) -> str | None:
    if value is None:
        return None
    return (date.fromisoformat(value) + timedelta(days=days)).isoformat()


def register_sqlite(dbapi_conn) -> None:  # noqa: ANN001
    dbapi_conn.create_function("satti_newid", 2, newid, deterministic=True)
    dbapi_conn.create_function("satti_shift_ts", 2, shift_timestamp, deterministic=True)
    dbapi_conn.create_function("satti_shift_date", 2, shift_date, deterministic=True)
