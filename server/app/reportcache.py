"""Кэш готовых отчётов магазина (AUD-12).

Кэшируются только готовые ответы (обычные словари), а не объекты базы: они привязаны к сессии запроса.
Сброс — при любой записи, которая меняет данные магазина (затраты, налог, комиссии, расходы, импорт, магазин, демо).
Ключ включает минуту текущего времени, поэтому границы периодов («7 дней», «месяц») не отстают больше чем на минуту.

Ограничения:
- кэш в памяти процесса: при нескольких процессах сброс в одном не виден в другом; тогда данные отстают не дольше TTL;
- TTL — страховка: даже если какой-то путь записи забудет сбросить кэш, ответ устареет не больше чем на TTL.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any

TTL_SECONDS = 60.0
MAX_SHOPS = 500

_lock = threading.Lock()
_versions: dict[str, int] = {}
_entries: dict[str, dict[str, Any]] = {}  # shop_id -> {"version": int, "items": {key: (ts, value)}}


def invalidate(shop_id: str) -> None:
    """Вызывается после записи, которая меняет данные магазина."""
    with _lock:
        _versions[shop_id] = _versions.get(shop_id, 0) + 1
        _entries.pop(shop_id, None)


def memo(shop_id: str, key: str, compute: Callable[[], Any]) -> Any:
    now = time.monotonic()
    with _lock:
        version = _versions.get(shop_id, 0)
        entry = _entries.get(shop_id)
        if entry is not None and entry["version"] == version:
            hit = entry["items"].get(key)
            if hit is not None and now - hit[0] < TTL_SECONDS:
                return hit[1]
    # версия читается до расчёта: если запись случится во время расчёта, результат не попадёт в кэш
    value = compute()
    with _lock:
        if _versions.get(shop_id, 0) != version:
            return value
        entry = _entries.get(shop_id)
        if entry is None or entry["version"] != version:
            if len(_entries) >= MAX_SHOPS:
                _entries.pop(next(iter(_entries)))
            entry = {"version": version, "items": {}}
            _entries[shop_id] = entry
        entry["items"][key] = (now, value)
    return value


def clear() -> None:
    """Для тестов."""
    with _lock:
        _versions.clear()
        _entries.clear()
