"""Простое ограничение частоты в памяти процесса (скользящее окно за час)."""

import os
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


def _trusted_proxies() -> frozenset[str]:
    raw = os.environ.get("SATTI_TRUSTED_PROXIES", "")
    return frozenset(p.strip() for p in raw.split(",") if p.strip())


def client_ip(request: Request) -> str:
    """Адрес клиента для лимитов (AUD-14).

    За обратным прокси все запросы приходят с адреса прокси, и лимит стал бы общим для всех.
    Заголовки X-Forwarded-For / X-Real-IP учитываются только если непосредственный адрес — доверенный прокси
    (SATTI_TRUSTED_PROXIES). Иначе клиент мог бы подделать адрес и обойти лимит.
    """
    peer = request.client.host if request.client else "unknown"
    trusted = _trusted_proxies()
    if peer not in trusted:
        return peer
    forwarded = [h.strip() for h in request.headers.get("x-forwarded-for", "").split(",") if h.strip()]
    for hop in reversed(forwarded):  # справа налево: первый адрес, который не наш прокси
        if hop not in trusted:
            return hop
    real = request.headers.get("x-real-ip", "").strip()
    return real or peer
