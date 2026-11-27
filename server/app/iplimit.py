"""Лимит запросов с одного адреса на входе сервера (К-21, часть 2, п.11) — в дополнение к лимитам в приложении.

Дешёвый счётчик в памяти процесса по минутам: без базы, чтобы наплыв запросов не нагружал PostgreSQL.
Адрес — тот же, что у остальных лимитов (`client_ip`, с учётом доверенного прокси Caddy).
Не ограничиваются: проверка здоровья (сторож), прайс-лист Kaspi (Kaspi забирает прайсы многих продавцов с немногих
адресов) и уведомления App Store и Google Play.
Порог — SATTI_IP_REQUESTS_PER_MINUTE (по умолчанию 300; 0 — выключено, так в тестах).
"""

from __future__ import annotations

import threading
import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from .config import settings
from .ratelimit import client_ip

EXEMPT_PREFIXES = ("/v1/health", "/v1/kaspi/price/", "/v1/store/")

_lock = threading.Lock()
_counts: dict[tuple[str, int], int] = {}
_last_cleanup = 0


def hit(ip: str, limit: int, now: float | None = None) -> bool:
    """True — запрос пропускается; False — порог за текущую минуту исчерпан."""
    global _last_cleanup
    minute = int((now if now is not None else time.time()) // 60)
    with _lock:
        if minute != _last_cleanup:  # раз в минуту выбрасываем старые окна — память не растёт
            for key in [k for k in _counts if k[1] < minute]:
                del _counts[key]
            _last_cleanup = minute
        n = _counts.get((ip, minute), 0)
        if n >= limit:
            return False
        _counts[(ip, minute)] = n + 1
        return True


def reset() -> None:
    with _lock:
        _counts.clear()


class IpRateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        limit = settings.ip_requests_per_minute
        path = request.url.path
        if limit > 0 and not path.startswith(EXEMPT_PREFIXES) and not hit(client_ip(request), limit):
            return JSONResponse(status_code=429, headers={"Retry-After": "60"}, content={"error": {
                "code": "rate_limited", "message": "Слишком много запросов. Подождите минуту.", "error_id": ""}})
        return await call_next(request)
