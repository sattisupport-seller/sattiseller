"""Мок Shop API Kaspi для тестов (этап 2, задача 2.5). Формат ответа — тот же, что ожидает клиент (см. kaspi_client.py).

Возможности: N товаров, заказы с состояниями (новые, принятые, выполненные, отменённые, возвращённые), отзыв токена,
ошибки по очереди (429, 500), изменение состояния заказа после выдачи.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import httpx

from app import kaspi_client

VALID_TOKEN = "mock-token-0123456789"
DAY_MS = 86_400_000


@dataclass
class MockKaspi:
    products: int = 1
    orders: list[dict] = field(default_factory=list)
    token: str = VALID_TOKEN
    fail_script: list[int] = field(default_factory=list)  # статусы ошибок по очереди, перед нормальным ответом
    requests_seen: int = 0
    fail_on_page: int | None = None  # эта страница отвечает 500 (сбой посреди синхронизации)

    def generate(self, count: int, *, now: datetime, days: int = 60, state_cycle=None, products: int | None = None) -> None:
        """Создаёт count заказов, равномерно за последние days дней. Товары — K0..K{products-1}."""
        states = state_cycle or ["COMPLETED", "NEW", "ACCEPTED_BY_MERCHANT", "CANCELLED", "RETURNED", "COMPLETED"]
        n_products = products or self.products
        base = int((now - timedelta(days=days)).timestamp() * 1000)
        span = days * DAY_MS
        for i in range(count):
            created = base + (span * i) // max(count, 1)
            entries = []
            for k in range(1 + i % 2):
                idx = (i * 7 + k) % n_products
                entries.append({"offerCode": f"K{idx}", "productName": f"Товар {idx}", "quantity": 1 + (i + k) % 3,
                                "basePrice": 1000 + 10 * idx})
            self.orders.append({
                "id": f"KC{i:08d}",
                "attributes": {"state": states[i % len(states)], "creationDate": created,
                               "completedDate": created + DAY_MS if states[i % len(states)] in ("COMPLETED", "RETURNED") else None,
                               "entries": entries},
            })

    def set_state(self, code: str, state: str) -> None:
        for o in self.orders:
            if o["id"] == code:
                o["attributes"]["state"] = state
                if state in ("COMPLETED", "RETURNED") and o["attributes"]["completedDate"] is None:
                    o["attributes"]["completedDate"] = o["attributes"]["creationDate"] + DAY_MS
                return
        raise KeyError(code)

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests_seen += 1
        if request.headers.get(kaspi_client.AUTH_HEADER) != self.token:
            return httpx.Response(401, json={"error": "unauthorized"})
        q_page = int(request.url.params.get("page[number]", "0"))
        if self.fail_on_page is not None and q_page == self.fail_on_page:
            return httpx.Response(500, json={"error": "down"})
        if self.fail_script:
            status = self.fail_script.pop(0)
            headers = {"Retry-After": "0"} if status == 429 else {}
            return httpx.Response(status, headers=headers, json={"error": "try later"})
        if not request.url.path.endswith("/" + kaspi_client.ORDERS_PATH):
            return httpx.Response(404, json={"error": "not found"})
        q = request.url.params
        since = int(q.get("filter[orders][creationDate][$ge]", "0"))
        page = int(q.get("page[number]", "0"))
        size = int(q.get("page[size]", str(kaspi_client.PAGE_SIZE)))
        rows = sorted((o for o in self.orders if o["attributes"]["creationDate"] >= since),
                      key=lambda o: o["attributes"]["creationDate"])
        chunk = rows[page * size:(page + 1) * size]
        return httpx.Response(200, content=json.dumps({"data": chunk}).encode(),
                              headers={"Content-Type": "application/json"})

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handler)


def now_utc() -> datetime:
    return datetime.now(timezone.utc)
