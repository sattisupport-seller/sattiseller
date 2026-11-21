"""Клиент Shop API Kaspi (этап 2, задача 2.1).

ВНИМАНИЕ: точные адреса, имена параметров и формат ответа взяты из открытых описаний и должны быть сверены
с официальной документацией guide.kaspi.kz до подключения реального магазина. Всё, что не подтверждено,
перечислено в docs/kaspi-assumptions.md. Эти значения собраны в одном месте (ниже), чтобы поправить их без
изменения логики.

Повторы: 429 и 5xx — повтор с паузой (Retry-After, иначе экспоненциально); 401/403 — токен не принят (повтора нет).
Соблюдение лимитов: между запросами не меньше MIN_INTERVAL_SECONDS.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import httpx

# --- UNVERIFIED: сверить с guide.kaspi.kz ---
BASE_URL = "https://kaspi.kz/shop/api/v2"
AUTH_HEADER = "X-Auth-Token"
ORDERS_PATH = "orders"
PAGE_SIZE = 100
MIN_INTERVAL_SECONDS = 0.25
MAX_ATTEMPTS = 4


class KaspiError(Exception):
    """Ошибка ответа Kaspi, которую нельзя исправить повтором."""


class KaspiAuthError(KaspiError):
    """Токен не принят Kaspi (отозван, неверный или истёк)."""


class KaspiUnavailable(KaspiError):
    """Kaspi не отвечает или отвечает ошибками после всех повторов."""


@dataclass
class OrderEntry:
    offer_code: str
    name: str
    qty: int
    unit_price: int  # тенге, целое


@dataclass
class KaspiOrder:
    code: str
    state: str
    created_ms: int
    completed_ms: int | None
    entries: list[OrderEntry] = field(default_factory=list)


def parse_order(item: dict) -> KaspiOrder:
    """Разбор заказа из ответа. Формат — предполагаемый (см. docs/kaspi-assumptions.md)."""
    attrs = item.get("attributes", {})
    entries = []
    for e in attrs.get("entries", []):
        qty = int(e.get("quantity", 1))
        price = int(round(float(e.get("basePrice", 0))))
        entries.append(OrderEntry(str(e["offerCode"]), str(e.get("productName", e["offerCode"])), qty, price))
    completed = attrs.get("completedDate")
    return KaspiOrder(
        code=str(item["id"]),
        state=str(attrs.get("state", "")),
        created_ms=int(attrs["creationDate"]),
        completed_ms=int(completed) if completed is not None else None,
        entries=entries,
    )


class KaspiClient:
    def __init__(self, token: str, *, base_url: str = BASE_URL, transport: httpx.BaseTransport | None = None,
                 min_interval: float = MIN_INTERVAL_SECONDS, max_attempts: int = MAX_ATTEMPTS,
                 sleep=time.sleep, clock=time.monotonic) -> None:
        self._http = httpx.Client(base_url=base_url, headers={AUTH_HEADER: token, "Accept": "application/json"},
                                  timeout=30.0, transport=transport)
        self._min_interval = min_interval
        self._max_attempts = max_attempts
        self._sleep = sleep
        self._clock = clock
        self._last_call: float | None = None

    def close(self) -> None:
        self._http.close()

    def _pace(self) -> None:
        if self._last_call is not None:
            wait = self._min_interval - (self._clock() - self._last_call)
            if wait > 0:
                self._sleep(wait)
        self._last_call = self._clock()

    def _backoff(self, attempt: int, retry_after: str | None) -> None:
        if retry_after and retry_after.isdigit():
            delay = min(60, int(retry_after))
        else:
            delay = min(30, 2 ** attempt)
        self._sleep(delay)

    def _get(self, path: str, params: dict) -> dict:
        last: KaspiError | None = None
        for attempt in range(self._max_attempts):
            self._pace()
            try:
                resp = self._http.get(path, params=params)
            except httpx.TransportError as exc:
                last = KaspiUnavailable(f"сеть: {type(exc).__name__}")
                self._backoff(attempt, None)
                continue
            if resp.status_code == 200:
                return resp.json()
            if resp.status_code in (401, 403):
                raise KaspiAuthError(f"HTTP {resp.status_code}")
            if resp.status_code == 429 or resp.status_code >= 500:
                last = KaspiUnavailable(f"HTTP {resp.status_code}")
                self._backoff(attempt, resp.headers.get("Retry-After"))
                continue
            raise KaspiError(f"HTTP {resp.status_code}")
        assert last is not None
        raise last

    def list_orders(self, since_ms: int, page: int) -> list[KaspiOrder]:
        """Заказы, созданные не раньше since_ms, страница page (с нуля). Пустой список — конец."""
        body = self._get(ORDERS_PATH, {
            "page[number]": page,
            "page[size]": PAGE_SIZE,
            "filter[orders][creationDate][ge]": since_ms,
        })
        return [parse_order(item) for item in body.get("data", [])]

    def ping(self, now_ms: int) -> None:
        """Проверка токена: короткий запрос за последние сутки."""
        self.list_orders(since_ms=now_ms - 86_400_000, page=0)
