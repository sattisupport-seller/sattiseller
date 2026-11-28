"""Клиент Shop API Kaspi (этап 2, задача 2.1).

ВНИМАНИЕ: точные адреса, имена параметров и формат ответа взяты из открытых описаний и должны быть сверены
с официальной документацией guide.kaspi.kz до подключения реального магазина. Всё, что не подтверждено,
перечислено в docs/kaspi-assumptions.md. Эти значения собраны в одном месте (ниже), чтобы поправить их без
изменения логики.

Повторы: 429 и 5xx — повтор с паузой (Retry-After, иначе экспоненциально); 401/403 — токен не принят (повтора нет).
Соблюдение лимитов: между запросами не меньше MIN_INTERVAL_SECONDS.
"""

from __future__ import annotations

import json
import logging
import re
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
MAX_PERIOD_MS = 14 * 86_400_000  # документация Kaspi (API по заказам): максимальный период поиска — 14 дней

log = logging.getLogger("satti.kaspi")


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
    handed_over_ms: int | None = None  # К-33 А4: передан в Kaspi Доставку (kaspiDelivery.courierTransmissionDate)


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
        # К-34: исход заказа — в `status` (COMPLETED, CANCELLED, RETURNED…); `state` — этап (NEW, PICKUP,
        # KASPI_DELIVERY, ARCHIVE…). Раньше читался только `state`: выданный и отменённый заказ (state=ARCHIVE)
        # стал бы «в работе». `state` — запасной вариант, если `status` в ответе нет.
        state=str(attrs.get("status") or attrs.get("state") or ""),
        created_ms=int(attrs["creationDate"]),
        completed_ms=int(completed) if completed is not None else None,
        entries=[],
        seller_delivery=seller_delivery,
        credit=attrs.get("paymentMode") == "PAY_WITH_CREDIT",
        returned_to_warehouse=(bool(attrs["returnedToWarehouse"]) if attrs.get("returnedToWarehouse") is not None
                               else None),
        handed_over_ms=_handed_over_ms(attrs),
    )


def _handed_over_ms(attrs: dict) -> int | None:
    """К-33 А4 / К-34: время передачи в Kaspi Доставку — атрибут заказа `courierTransmissionDate` (документация
    Kaspi, список атрибутов заказа); на всякий случай — и вложенный `kaspiDelivery.courierTransmissionDate`.
    None — не передан, своя доставка или самовывоз (тогда Kaspi вернёт остаток сам).
    Этап `state=KASPI_DELIVERY` признаком не считается: он, по-видимому, включает и «Упаковку», где Kaspi возвращает
    остаток сам (гид q3694). Сверить на реальном магазине (KASPI_TEST.md)."""
    candidates = [attrs.get("courierTransmissionDate")]
    kd = attrs.get("kaspiDelivery")
    if isinstance(kd, dict):
        candidates.append(kd.get("courierTransmissionDate"))
    for raw in candidates:
        if raw not in (None, "", 0):
            try:
                return int(raw)
            except (TypeError, ValueError):
                return 0
    return None


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
        self.skipped = 0  # К-33 А1: сколько записей Kaspi пропущено из-за неожиданного формата
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
                body = resp.json()
                self._record_shape(path, body)
                return body
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
        try:
            total_n = int(total) if total is not None else None
        except (TypeError, ValueError):
            total_n = None
        data = body.get("data", [])
        self._observe(data)
        return self._parse_each(data, parse_order, "order"), total_n

    # К-37 п.4: какие поля и статусы реально присылает Kaspi — в журнал раз за синхронизацию (client живёт одну
    # синхронизацию). Только названия полей и служебные значения status/state, без данных покупателя и без токена.
    OBSERVED_ENUMS = ("status", "state", "deliveryMode", "paymentMode", "creditTerm", "isKaspiDelivery",
                      "cancellationReason", "cancelReason")

    def _observe(self, items) -> None:
        if not isinstance(items, list):
            return
        if not hasattr(self, "_seen_fields"):
            self._seen_fields: set[str] = set()
            self._seen_values: dict[str, set[str]] = {}
            self._transmission: dict[str, list[int]] = {}
        for item in items:
            attrs = item.get("attributes") if isinstance(item, dict) else None
            if not isinstance(attrs, dict):
                continue
            self._seen_fields.update(str(k) for k in attrs)
            for key in self.OBSERVED_ENUMS:
                if key in attrs and not isinstance(attrs[key], (dict, list)):
                    self._seen_values.setdefault(key, set()).add(str(attrs[key])[:40])
            # KASPI_TEST §9: есть ли признак передачи в Kaspi Доставку — по исходу заказа (с полем / всего)
            outcome = str(attrs.get("status") or attrs.get("state") or "?")[:40]
            delivery = attrs.get("kaspiDelivery") if isinstance(attrs.get("kaspiDelivery"), dict) else {}
            has = bool(attrs.get("courierTransmissionDate") or delivery.get("courierTransmissionDate"))
            cnt = self._transmission.setdefault(outcome, [0, 0])
            cnt[0] += int(has)
            cnt[1] += 1

    def observed_summary(self) -> str | None:
        if not getattr(self, "_seen_fields", None):
            return None
        values = "; ".join(f"{k}={sorted(v)}" for k, v in sorted(self._seen_values.items()))
        handed = ", ".join(f"{k} {a}/{b}" for k, (a, b) in sorted(self._transmission.items()))
        return f"fields={sorted(self._seen_fields)} values: {values}; courierTransmissionDate: {handed}"

    # KASPI_TEST §9 и К-37 п.4: структура ответов Kaspi по видам запросов — только названия полей и типы значений,
    # никаких значений (ни данных покупателя, ни сумм, ни токена). Объединяется по всем ответам одной синхронизации.
    _ID_SEGMENT = re.compile(r"^(?=.*\d)[A-Za-z0-9_=-]{4,}$")

    @classmethod
    def _path_kind(cls, path: str) -> str:
        segs = path.split("?")[0].strip("/").split("/")
        return "/".join("{id}" if cls._ID_SEGMENT.match(s) else s for s in segs)

    @classmethod
    def _shape(cls, value, depth: int = 0):
        if depth > 6:
            return "…"
        if isinstance(value, dict):
            return {str(k)[:60]: cls._shape(v, depth + 1) for k, v in list(value.items())[:80]}
        if isinstance(value, list):
            merged = None
            for v in value[:200]:
                merged = cls._merge(merged, cls._shape(v, depth + 1))
            return [merged] if merged is not None else []
        if value is None:
            return "null"
        return {bool: "bool", int: "int", float: "float", str: "str"}.get(type(value), type(value).__name__)

    @classmethod
    def _merge(cls, a, b):
        if a is None:
            return b
        if b is None:
            return a
        if isinstance(a, dict) and isinstance(b, dict):
            out = dict(a)
            for k, v in b.items():
                out[k] = cls._merge(out.get(k), v)
            return out
        if isinstance(a, list) and isinstance(b, list):
            inner = cls._merge(a[0] if a else None, b[0] if b else None)
            return [inner] if inner is not None else []
        if isinstance(a, (dict, list)) or isinstance(b, (dict, list)):
            return "mixed"
        return a if a == b else "|".join(sorted(set(a.split("|")) | set(b.split("|"))))

    def _record_shape(self, path: str, body) -> None:
        if not hasattr(self, "_shapes"):
            self._shapes: dict[str, object] = {}
        kind = self._path_kind(path)
        self._shapes[kind] = self._merge(self._shapes.get(kind), self._shape(body))

    def observed_shapes(self) -> dict[str, str]:
        """Вид запроса → структура ответа одной строкой JSON (для журнала)."""
        return {k: json.dumps(v, ensure_ascii=False, sort_keys=True)[:6000]
                for k, v in sorted(getattr(self, "_shapes", {}).items())}

    def _parse_each(self, items, parse, kind: str):
        """К-33 А1: странная запись не роняет загрузку — пропускаем, пишем в журнал (без данных покупателя и токена)."""
        out = []
        for item in items if isinstance(items, list) else []:
            try:
                out.append(parse(item))
            except (KeyError, TypeError, ValueError, AttributeError) as exc:
                self.skipped += 1
                ident = item.get("id") if isinstance(item, dict) else None
                log.warning("kaspi %s skipped: id=%s %s", kind, ident, type(exc).__name__)
        return out

    def order_entries(self, order_code: str) -> list[OrderEntry]:
        """Позиции заказа: GET /orders/{code}/entries (документация: раздел «Состав заказа», q3203)."""
        body = self._get(f"{ORDERS_PATH}/{order_code}/entries", {})
        for item in body.get("data", []):
            point = ((item.get("relationships") or {}).get("deliveryPointOfService") or {}).get("data") or {}
            if point.get("id"):
                self.last_point_id = str(point["id"])
        return self._parse_each(body.get("data", []), parse_entry, "entry")

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
