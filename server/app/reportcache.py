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
from collections import OrderedDict
from collections.abc import Callable
from typing import Any

TTL_SECONDS = 60.0
MAX_SHOPS = 500
# 1.17: исходные данные магазина (загруженные строки и факты по строкам). Тяжёлая часть отчётов: 10 000 заказов
# грузятся около секунды. Хранятся только простые копии (не объекты сессии), число магазинов ограничено.
SNAPSHOT_TTL_SECONDS = 300.0
MAX_SNAPSHOTS = 10  # магазин на 10 000 заказов занимает около 26 МБ; 10 штук — до 260 МБ памяти процесса

_lock = threading.Lock()
_versions: dict[str, int] = {}
_entries: dict[str, dict[str, Any]] = {}  # shop_id -> {"version": int, "items": {key: (ts, value)}}
_snapshots: OrderedDict[str, tuple[int, float, Any]] = OrderedDict()  # shop_id -> (версия, время, данные)


def invalidate(shop_id: str) -> None:
    """Вызывается после записи, которая меняет данные магазина."""
    with _lock:
        _versions[shop_id] = _versions.get(shop_id, 0) + 1
        _entries.pop(shop_id, None)
        _snapshots.pop(shop_id, None)


def snapshot(shop_id: str, compute: Callable[[], Any]) -> Any:
    """Исходные данные магазина: из кэша, если версия не менялась и не прошло SNAPSHOT_TTL_SECONDS."""
    now = time.monotonic()
    with _lock:
        version = _versions.get(shop_id, 0)
        hit = _snapshots.get(shop_id)
        if hit is not None and hit[0] == version and now - hit[1] < SNAPSHOT_TTL_SECONDS:
            _snapshots.move_to_end(shop_id)
            return hit[2]
    value = compute()
    with _lock:
        if _versions.get(shop_id, 0) == version:
            _snapshots[shop_id] = (version, now, value)
            _snapshots.move_to_end(shop_id)
            while len(_snapshots) > MAX_SNAPSHOTS:
                _snapshots.popitem(last=False)
    return value


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
        _snapshots.clear()
