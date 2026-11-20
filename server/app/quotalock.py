"""Блокировка на время проверки и списания квоты ИИ (AUD-17).

Без неё два параллельных вопроса оба видят остаток 1 и оба проходят — лимит превышается.
Блокировка держит весь путь «проверка → ответ → запись события» для одного субъекта квоты
(пользователь, а для демо — магазин). Работает внутри одного процесса; несколько процессов
нужно будет согласовать общим хранилищем вместе с лимитами (AUD-14, часть 2).
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager

_guard = threading.Lock()
_locks: dict[str, threading.Lock] = {}


@contextmanager
def quota_guard(subject: str) -> Iterator[None]:
    with _guard:
        lock = _locks.setdefault(subject, threading.Lock())
    with lock:
        yield
