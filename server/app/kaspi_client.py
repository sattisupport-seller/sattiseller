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
    """Позиция заказа по документации Kaspi (сверка 22.11): у позиции нет артикула продавца.
    Артикул получаем отдельно: позиция → product (masterproducts) → merchantProduct (код)."""
    entry_id: str
    qty: int
    unit_price: int  # тенге, целое (basePrice)
    category: str | None = None  # категория из позиции Kaspi (К-16.2): название, иначе код


@dataclass
class KaspiOrder:
    code: str
    state: str
    created_ms: int
    completed_ms: int | None
    entries: list[OrderEntry] = field(default_factory=list)
    seller_delivery: int | None = None  # deliveryCostForSeller: доставка, которую оплачивает продавец (тенге)
    credit: bool = False  # paymentMode == PAY_WITH_CREDIT: рассрочка/кредит, комиссия отличается
    returned_to_warehouse: bool | None = None  # returnedToWarehouse: товар вернулся на склад продавца (возврат)


def parse_order(item: dict) -> KaspiOrder:
    """Разбор заказа из списка. Позиции приходят отдельным запросом (см. KaspiClient.order_entries)."""
    attrs = item.get("attributes", {})
    completed = attrs.get("completedDate")
    raw_delivery = attrs.get("deliveryCostForSeller")
    seller_delivery = None
    if raw_delivery is not None:
        try:
            seller_delivery = int(round(float(raw_delivery)))
        except (TypeError, ValueError):
            seller_delivery = None
    return KaspiOrder(
        code=str(item["id"]),
        state=str(attrs.get("state", "")),
        created_ms=int(attrs["creationDate"]),
        completed_ms=int(completed) if completed is not None else None,
        entries=[],
        seller_delivery=seller_delivery,
        credit=attrs.get("paymentMode") == "PAY_WITH_CREDIT",
        returned_to_warehouse=(bool(attrs["returnedToWarehouse"]) if attrs.get("returnedToWarehouse") is not None
                               else None),
    )


def parse_entry(item: dict) -> OrderEntry:
    """Позиция из /orders/{id}/entries. Поля quantity и basePrice — по документации; id позиции — из ответа."""
    attrs = item.get("attributes", {})
    cat = attrs.get("category")
    category = None
    if isinstance(cat, dict):
        category = str(cat.get("title") or cat.get("code") or "").strip() or None
    return OrderEntry(
        entry_id=str(item["id"]),
        qty=int(attrs.get("quantity", 1)),
        unit_price=int(round(float(attrs.get("basePrice", 0)))),
        category=category,
    )


class KaspiClient:
    def __init__(self, token: str, *, base_url: str = BASE_URL, transport: httpx.BaseTransport | None = None,
                 min_interval: float = MIN_INTERVAL_SECONDS, max_attempts: int = MAX_ATTEMPTS,
                 sleep=time.sleep, clock=time.monotonic) -> None:
        # Content-Type — как в примерах документации Kaspi (JSON:API)
        self.last_point_id: str | None = None  # подсказка кода склада из связи позиции (deliveryPointOfService)
        self._sku_by_entry: dict[str, str | None] = {}
        self._sku_by_master: dict[str, str | None] = {}
        self._http = httpx.Client(base_url=base_url, headers={AUTH_HEADER: token, "Accept": "application/json", "Content-Type": "application/vnd.api+json"},
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

    def list_orders(self, since_ms: int, page: int, until_ms: int | None = None) -> list[KaspiOrder]:
        """Заказы, созданные не раньше since_ms (и не позже until_ms), страница page (с нуля). Пустой список — конец."""
        return self.list_orders_page(since_ms, page, until_ms)[0]

    def list_orders_page(self, since_ms: int, page: int, until_ms: int | None = None) -> tuple[list[KaspiOrder], int | None]:
        """Как list_orders, плюс общее число заказов из meta.totalCount (для прогресса загрузки, К-18.3)."""
        params = {
            "page[number]": page,
            "page[size]": PAGE_SIZE,
            "filter[orders][creationDate][$ge]": since_ms,  # документация Kaspi: [$ge], в миллисекундах
        }
        if until_ms is not None:
            params["filter[orders][creationDate][$le]"] = until_ms  # документация Kaspi: [$le]
        body = self._get(ORDERS_PATH, params)
        total = (body.get("meta") or {}).get("totalCount")
        return [parse_order(item) for item in body.get("data", [])], (int(total) if total is not None else None)

    def order_entries(self, order_code: str) -> list[OrderEntry]:
        """Позиции заказа: GET /orders/{code}/entries (документация: раздел «Состав заказа», q3203)."""
        body = self._get(f"{ORDERS_PATH}/{order_code}/entries", {})
        for item in body.get("data", []):
            point = ((item.get("relationships") or {}).get("deliveryPointOfService") or {}).get("data") or {}
            if point.get("id"):
                self.last_point_id = str(point["id"])
        return [parse_entry(item) for item in body.get("data", [])]

    def entry_sku(self, entry_id: str) -> str | None:
        """Артикул продавца для позиции: orderentries/{id}/product → masterproducts/{id}/merchantProduct.
        Формат ответов — по связям из документации; код берётся из attributes.code. Результат кэшируется на клиенте."""
        return self.entry_product(entry_id)[0]

    def entry_product(self, entry_id: str) -> tuple[str | None, str | None]:
        """(артикул, название) товара позиции (К-16.1). Название — из merchantProduct или masterproducts (attributes.name);
        формат ответа по связям документации, полный пример не разобран. Кэшируется на клиенте."""
        if entry_id in self._sku_by_entry:
            return self._sku_by_entry[entry_id]
        sku = name = None
        product = self._get(f"orderentries/{entry_id}/product", {}).get("data") or {}
        master_id = product.get("id")
        if master_id:
            if master_id not in self._sku_by_master:
                mp = self._get(f"masterproducts/{master_id}/merchantProduct", {}).get("data") or {}
                attrs = mp.get("attributes") or {}
                code = str(attrs.get("code") or "") or None
                title = str(attrs.get("name") or "").strip() or None
                if title is None:
                    master = self._get(f"masterproducts/{master_id}", {}).get("data") or {}
                    title = str((master.get("attributes") or {}).get("name") or "").strip() or None
                self._sku_by_master[master_id] = (code, title)
            sku, name = self._sku_by_master[master_id]
        self._sku_by_entry[entry_id] = (sku, name)
        return sku, name

    def order_by_code(self, code: str) -> KaspiOrder | None:
        """Один заказ по номеру: фильтр filter[orders][code] (раздел «Заказы», q3202). Нужен для открытых заказов (К-19)."""
        body = self._get(ORDERS_PATH, {"filter[orders][code]": code})
        for item in body.get("data", []):
            if str(item.get("id")) == code:
                return parse_order(item)
        return None

    def ping(self, now_ms: int) -> None:
        """Проверка токена: короткий запрос за последние сутки."""
        self.list_orders(since_ms=now_ms - 86_400_000, page=0)
