"""Мок Shop API Kaspi для тестов (этап 2, задача 2.5). Формат ответа — тот же, что ожидает клиент (см. kaspi_client.py).

Возможности: N товаров, заказы с состояниями (новые, принятые, выполненные, отменённые, возвращённые), отзыв токена,
ошибки по очереди (429, 500), изменение состояния заказа после выдачи.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import httpx

from app import kaspi_client

VALID_TOKEN = "mock-token-0123456789"
DAY_MS = 86_400_000


@dataclass
class MockKaspi:
    """Мок по документации Kaspi (сверка 22.11): список заказов без позиций; позиции — /orders/{id}/entries;
    артикул — orderentries/{id}/product → masterproducts/{id}/merchantProduct (код = attributes.code)."""

    products: int = 1
    orders: list[dict] = field(default_factory=list)
    entries: dict = field(default_factory=dict)  # код заказа -> список позиций {id, idx, qty, basePrice}
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
            code = f"KC{i:08d}"
            state = states[i % len(states)]
            rows = []
            for k in range(1 + i % 2):
                idx = (i * 7 + k) % n_products
                rows.append({"id": f"E{i:08d}{k}", "idx": idx, "qty": 1 + (i + k) % 3, "basePrice": 1000 + 10 * idx})
            self.entries[code] = rows
            self.orders.append({
                "id": code, "type": "orders",
                "attributes": {"state": state, "creationDate": created,
                               "completedDate": created + DAY_MS if state in ("COMPLETED", "RETURNED") else None,
                               "paymentMode": "PAY_WITH_CREDIT" if i % 4 == 1 else "PREPAID",
                               **({"deliveryCostForSeller": 500} if i % 3 == 0 else {})},
                "relationships": {"entries": {"links": {"related": f"/orders/{code}/entries"}}},
            })

    def set_state(self, code: str, state: str) -> None:
        for o in self.orders:
            if o["id"] == code:
                o["attributes"]["state"] = state
                if state in ("COMPLETED", "RETURNED") and o["attributes"]["completedDate"] is None:
                    o["attributes"]["completedDate"] = o["attributes"]["creationDate"] + DAY_MS
                return
        raise KeyError(code)

    def partial_cancel(self, code: str, entry_index: int, remained: int) -> None:
        """Частичная отмена: в позиции остаётся remained штук (документация: orderPartialCancel)."""
        self.entries[code][entry_index]["qty"] = remained

    def _entry_by_id(self, entry_id: str) -> dict:
        for rows in self.entries.values():
            for row in rows:
                if row["id"] == entry_id:
                    return row
        raise KeyError(entry_id)

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests_seen += 1
        if request.headers.get(kaspi_client.AUTH_HEADER) != self.token:
            return httpx.Response(401, json={"error": "unauthorized"})
        path = request.url.path
        q_page = int(request.url.params.get("page[number]", "0"))
        if self.fail_on_page is not None and q_page == self.fail_on_page and path.endswith("/orders"):
            return httpx.Response(500, json={"error": "down"})
        if self.fail_script:
            status = self.fail_script.pop(0)
            headers = {"Retry-After": "0"} if status == 429 else {}
            return httpx.Response(status, headers=headers, json={"error": "try later"})
        m = re.search(r"/orders/([^/]+)/entries$", path)
        if m:
            rows = self.entries.get(m.group(1), [])
            data = [{"type": "orderentries", "id": r["id"],
                     "attributes": {"quantity": r["qty"], "basePrice": r["basePrice"],
                                    "category": {"code": "C1", "title": "Посуда для кухни"}},
                     "relationships": {"product": {"links": {"related": f"/orderentries/{r['id']}/product"}},
                                       "deliveryPointOfService": {"data": {"type": "pointofservices", "id": "PP1"}}}}
                    for r in rows]
            return self._json({"data": data})
        m = re.search(r"/orderentries/([^/]+)/product$", path)
        if m:
            row = self._entry_by_id(m.group(1))
            return self._json({"data": {"type": "masterproducts", "id": f"M{row['idx']}"}})
        m = re.search(r"/masterproducts/([^/]+)/merchantProduct$", path)
        if m:
            idx = m.group(1)[1:]
            return self._json({"data": {"type": "merchantproducts", "id": f"MP{idx}",
                                        "attributes": {"code": f"K{idx}", "name": f"Товар K{idx} из кабинета"}}})
        if not path.endswith("/" + kaspi_client.ORDERS_PATH):
            return httpx.Response(404, json={"error": "not found"})
        q = request.url.params
        if "filter[orders][code]" in q:  # заказ по номеру (К-19)
            code = q["filter[orders][code]"]
            return self._json({"data": [o for o in self.orders if o["id"] == code]})
        since = int(q.get("filter[orders][creationDate][$ge]", "0"))
        until = q.get("filter[orders][creationDate][$le]")
        page = int(q.get("page[number]", "0"))
        size = int(q.get("page[size]", str(kaspi_client.PAGE_SIZE)))
        rows = sorted((o for o in self.orders if o["attributes"]["creationDate"] >= since
                       and (until is None or o["attributes"]["creationDate"] <= int(until))),
                      key=lambda o: o["attributes"]["creationDate"])
        chunk = rows[page * size:(page + 1) * size]
        return self._json({"data": chunk, "meta": {"totalCount": len(rows), "pageCount": -(-len(rows) // size)}})

    @staticmethod
    def _json(body: dict) -> httpx.Response:
        return httpx.Response(200, content=json.dumps(body).encode(), headers={"Content-Type": "application/json"})

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handler)


def now_utc() -> datetime:
    return datetime.now(timezone.utc)
