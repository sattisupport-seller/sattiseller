"""Простое ограничение частоты в памяти процесса (скользящее окно за час)."""

import time
from collections import defaultdict, deque

from fastapi import Request

_hits: dict[str, deque[float]] = defaultdict(deque)
WINDOW_SECONDS = 3600


def allow(key: str, limit: int, window: int = WINDOW_SECONDS) -> bool:
    now = time.monotonic()
    q = _hits[key]
    while q and now - q[0] > window:
        q.popleft()
    if len(q) >= limit:
        return False
    q.append(now)
    return True


def reset() -> None:
    _hits.clear()


def client_ip(request: Request) -> str:
    """Адрес клиента для лимитов. AUD-14: здесь же будет разбор адреса за доверенным прокси."""
    return request.client.host if request.client else "unknown"
