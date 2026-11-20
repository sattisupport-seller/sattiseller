"""Отчёты: обзор, прибыль, заказы, товары, экспресс-аналитика для помощника.

Вся арифметика здесь и в finance.py. Приложение и ИИ только показывают готовые числа.

Привязка к периодам (docs/spec.md, 6.4):
  продажа   — к дате выдачи заказа (completed_at, по часовому поясу магазина);
  возврат   — к дате подтверждения возврата; уменьшает показатели того периода, куда попал;
  отмена, ожидание, в работе — к дате создания заказа (только в «сумме заказов» и отменах).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from fractions import Fraction
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession
from sqlalchemy.orm import selectinload

from .finance import Return, SaleLine, return_is_known, return_profit_delta, sale_result
from .models import (
    CommissionPreset,
    ExpenseEntry,
    Order,
    OrderItem,
    Product,
    ProductCostVersion,
    Shop,
    TaxRate,
)
from .money import apply_bp, round_half_up_div
from .periods import Period

SALE_STATUSES = {"completed", "returned", "partial_return"}
CANCEL_STATUSES = {"cancelled"}
OPEN_STATUSES = {"pending", "in_progress"}


# ---------- загрузка данных магазина ----------

@dataclass
class ShopData:
    shop: Shop
    tz: ZoneInfo
    products: dict[str, Product]
    versions: dict[str, list[ProductCostVersion]]
    presets: dict[str, list[CommissionPreset]]
    orders: list[Order]
    expenses: list[ExpenseEntry]
    tax_rates: list[TaxRate] = field(default_factory=list)


def load_shop(db: DbSession, shop: Shop) -> ShopData:
    products = {p.id: p for p in db.scalars(select(Product).where(Product.shop_id == shop.id)).all()}
    versions: dict[str, list[ProductCostVersion]] = defaultdict(list)
    for v in db.scalars(
        select(ProductCostVersion).where(ProductCostVersion.shop_id == shop.id, ProductCostVersion.cancelled.is_(False))
    ).all():
        versions[v.product_id].append(v)
    for lst in versions.values():
        lst.sort(key=lambda v: (v.effective_from or date.min, v.created_at))
    presets: dict[str, list[CommissionPreset]] = defaultdict(list)
    for pr in db.scalars(select(CommissionPreset).where(CommissionPreset.shop_id == shop.id)).all():
        presets[pr.category].append(pr)
    for lst in presets.values():
        lst.sort(key=lambda p: p.effective_from or date.min)
    orders = db.scalars(
        select(Order).where(Order.shop_id == shop.id).options(
            selectinload(Order.items).selectinload(OrderItem.returns)
        ).order_by(Order.created_at)
    ).all()
    expenses = db.scalars(select(ExpenseEntry).where(ExpenseEntry.shop_id == shop.id)).all()
    tax_rates = sorted(
        db.scalars(select(TaxRate).where(TaxRate.shop_id == shop.id)).all(),
        key=lambda t: (t.effective_from or date.min, t.created_at),
    )
    return ShopData(shop, ZoneInfo(shop.timezone), products, dict(versions), dict(presets), orders, expenses,
                    tax_rates)


def local_day(dt: datetime, tz: ZoneInfo) -> date:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(tz).date()


def unit_cost_on(versions: list[ProductCostVersion], day: date) -> int | None:
    applicable = [v for v in versions if v.effective_from is None or v.effective_from <= day]
    if not applicable:
        return None
    return applicable[-1].landed_unit_minor


def active_cost(versions: list[ProductCostVersion], day: date) -> ProductCostVersion | None:
    applicable = [v for v in versions if v.effective_from is None or v.effective_from <= day]
    return applicable[-1] if applicable else None


def rate_on(presets: list[CommissionPreset], day: date) -> CommissionPreset | None:
    applicable = [p for p in presets if p.effective_from is None or p.effective_from <= day]
    return applicable[-1] if applicable else None


def tax_rate_bp_on(rates: list[TaxRate], day: date) -> int | None:
    """Ставка налога на дату (ТЗ 2.1, раздел 7.1). None — налог не учитывается."""
    applicable = [t for t in rates if t.effective_from is None or t.effective_from <= day]
    return applicable[-1].rate_bp if applicable else None


# ---------- факты по строкам ----------

@dataclass
class ReturnFact:
    day: date
    qty: int
    refund: int
    delta: int | None  # изменение прибыли; None — неизвестно
    known: bool
    raw: Return


@dataclass
class ItemFact:
    product_id: str
    sku: str
    name: str
    category: str
    order_id: str
    order_number: str
    status: str
    created_day: date
    sale_day: date | None
    qty: int
    unit_price: int
    gross: int
    unit_cost: int | None
    rate_bp: int | None
    rate_source: str | None
    cost_source: str | None
    sale_profit: int | None
    landed: int | None
    commission: int | None
    delivery: int | None
    returns: list[ReturnFact] = field(default_factory=list)
    tax_rate_bp: int | None = None  # ставка налога на дату заказа; None — налог не учитывается
    tax: int = 0  # налог с продажи строки

    @property
    def is_sale(self) -> bool:
        return self.status in SALE_STATUSES

    @property
    def complete(self) -> bool:
        return self.is_sale and self.sale_profit is not None and all(r.known for r in self.returns)


def _tax_on_return(refund: int | None, rates: list[TaxRate], day: date) -> int:
    """Налог, возвращённый с суммы возврата; округляется отдельно (ТЗ 2.1, раздел 7.1)."""
    rate = tax_rate_bp_on(rates, day)
    if rate is None or refund is None:
        return 0
    return apply_bp(refund, rate)


def build_facts(data: ShopData) -> list[ItemFact]:
    facts: list[ItemFact] = []
    for order in data.orders:
        sale_day = local_day(order.completed_at, data.tz) if order.completed_at else None
        created_day = local_day(order.created_at, data.tz)
        for item in order.items:
            product = data.products.get(item.product_id)
            if product is None:
                continue
            basis_day = sale_day or created_day
            unit_cost = unit_cost_on(data.versions.get(product.id, []), basis_day)
            cost_version = active_cost(data.versions.get(product.id, []), basis_day)
            preset = rate_on(data.presets.get(product.category, []), basis_day)
            tax_rate = tax_rate_bp_on(data.tax_rates, basis_day)
            rate = item.commission_rate_bp if item.commission_rate_bp is not None else (
                preset.rate_bp if preset else None
            )
            rate_source = "override" if item.commission_rate_bp is not None else (
                ("demo" if preset.demo else preset.source) if preset else None
            )
            line = SaleLine(
                qty=item.qty,
                unit_price_minor=item.unit_price_minor,
                status="completed" if order.status in SALE_STATUSES else order.status,
                unit_cost_minor=unit_cost,
                buyer_delivery_minor=item.buyer_delivery_minor,
                commission_rate_bp=rate,
                returns=[],
                tax_rate_bp=tax_rate,
            )
            sale = sale_result(line)
            returns: list[ReturnFact] = []
            for ev in item.returns:
                raw = Return(
                    returned_qty=ev.returned_qty,
                    refund_minor=ev.refund_minor,
                    commission_returned_minor=ev.commission_returned_minor,
                    delivery_returned_minor=ev.delivery_returned_minor,
                    reverse_delivery_minor=ev.reverse_delivery_minor,
                    goods_sellable=ev.goods_sellable,
                    tax_returned_minor=_tax_on_return(ev.refund_minor, data.tax_rates,
                                                      local_day(ev.confirmed_at, data.tz)),
                )
                known = return_is_known(raw)
                delta = return_profit_delta(line, raw) if item.returns else None
                returns.append(ReturnFact(
                    day=local_day(ev.confirmed_at, data.tz),
                    qty=ev.returned_qty,
                    refund=ev.refund_minor or 0,
                    delta=delta,
                    known=known and delta is not None,
                    raw=raw,
                ))
            facts.append(ItemFact(
                product_id=product.id, sku=product.sku, name=product.name, category=product.category,
                order_id=order.id, order_number=order.number, status=order.status,
                created_day=created_day, sale_day=sale_day, qty=item.qty,
                unit_price=item.unit_price_minor, gross=item.unit_price_minor * item.qty,
                unit_cost=unit_cost, rate_bp=rate, rate_source=rate_source,
                cost_source=cost_version.source if cost_version else None,
                sale_profit=sale.profit_minor, landed=sale.landed_minor,
                commission=sale.commission_minor, delivery=sale.delivery_minor,
                returns=returns, tax_rate_bp=tax_rate, tax=sale.tax_minor,
            ))
    return facts


# ---------- агрегаты за период ----------

@dataclass
class Metrics:
    period: Period
    orders_count: int = 0
    orders_sum: int = 0
    cancelled_count: int = 0
    cancelled_sum: int = 0
    returns_count: int = 0
    net_sales: int = 0  # чистые продажи всех строк
    net_complete: int = 0  # чистые продажи полного набора
    profit: int = 0  # прибыль полного набора
    coverage_bp: int = 0
    margin_bp: int = 0
    units_sold: int = 0
    # компоненты полного набора (для лесенки прибыли)
    gross_c: int = 0
    landed_c: int = 0
    commission_c: int = 0
    delivery_c: int = 0
    refunds_c: int = 0
    recovered_c: int = 0
    comm_returned_c: int = 0
    extra_delivery_c: int = 0
    tax_c: int = 0  # налог с продаж полного набора
    tax_returned_c: int = 0  # налог, возвращённый с возвратов полного набора
    tax_rates_seen: set[int] = field(default_factory=set)  # ставки, применённые в периоде
    day_net: dict[date, int] = field(default_factory=lambda: defaultdict(int))
    day_profit: dict[date, int] = field(default_factory=lambda: defaultdict(int))
    day_units: dict[date, int] = field(default_factory=lambda: defaultdict(int))


def _in(period: Period, day: date | None) -> bool:
    return day is not None and period.contains(day)


def metrics_for(facts: list[ItemFact], orders: list[Order], tz: ZoneInfo, period: Period) -> Metrics:
    m = Metrics(period=period)
    seen_orders: set[str] = set()
    for o in orders:
        if _in(period, local_day(o.created_at, tz)):
            m.orders_count += 1
            m.orders_sum += sum(i.unit_price_minor * i.qty for i in o.items)
            if o.status in CANCEL_STATUSES:
                m.cancelled_count += 1
                m.cancelled_sum += sum(i.unit_price_minor * i.qty for i in o.items)
        seen_orders.add(o.id)

    for f in facts:
        if not f.is_sale:
            continue
        if _in(period, f.sale_day):
            m.units_sold += f.qty
            m.day_units[f.sale_day] += f.qty
            m.net_sales += f.gross
            m.day_net[f.sale_day] += f.gross
            if f.complete:
                m.net_complete += f.gross
                m.gross_c += f.gross
                m.landed_c += f.landed or 0
                m.commission_c += f.commission or 0
                m.delivery_c += f.delivery or 0
                m.tax_c += f.tax
                if f.tax_rate_bp is not None:
                    m.tax_rates_seen.add(f.tax_rate_bp)
                m.profit += f.sale_profit or 0
                m.day_profit[f.sale_day] += f.sale_profit or 0
        for r in f.returns:
            if not _in(period, r.day):
                continue
            m.returns_count += 1
            m.net_sales -= r.refund
            m.day_net[r.day] -= r.refund
            if f.complete:
                raw = r.raw
                m.net_complete -= r.refund
                m.refunds_c += r.refund
                if raw.goods_sellable and f.unit_cost is not None:
                    m.recovered_c += f.unit_cost * raw.returned_qty
                m.comm_returned_c += raw.commission_returned_minor or 0
                m.extra_delivery_c += (raw.reverse_delivery_minor or 0) - (raw.delivery_returned_minor or 0)
                m.tax_returned_c += raw.tax_returned_minor
                m.profit += r.delta or 0
                m.day_profit[r.day] += r.delta or 0

    m.coverage_bp = round_half_up_div(m.net_complete * 10_000, m.net_sales) if m.net_sales > 0 else 0
    m.margin_bp = round_half_up_div(m.profit * 10_000, m.net_complete) if m.net_complete > 0 else 0
    return m


def expenses_in(expenses: list[ExpenseEntry], period: Period) -> dict[str, int]:
    """Расходы магазина, распределённые по дням пропорционально; остаток округления — на последний день."""
    out = {"ads": 0, "other": 0}
    for e in expenses:
        total_days = (e.period_end - e.period_start).days + 1
        overlap_start = max(e.period_start, period.start)
        overlap_end = min(e.period_end, period.end)
        if overlap_end < overlap_start:
            continue
        overlap_days = (overlap_end - overlap_start).days + 1
        if total_days <= 0:
            continue
        share = round_half_up_div(e.amount_minor * overlap_days, total_days)
        out[e.kind] = out.get(e.kind, 0) + share
    return out


# ---------- товары ----------

@dataclass
class ProductStats:
    product: Product
    has_cost: bool
    sold_qty: int
    returned_qty: int
    net_sales: int
    profit: int | None  # None — данных полного набора нет
    margin_bp: int | None
    complete: bool


def product_stats(data: ShopData, facts: list[ItemFact], period: Period) -> dict[str, ProductStats]:
    acc: dict[str, dict] = defaultdict(lambda: {"sold": 0, "returned": 0, "net": 0, "profit": 0,
                                                 "net_c": 0, "complete_any": False, "unknown": False})
    for f in facts:
        if not f.is_sale:
            continue
        a = acc[f.product_id]
        if _in(period, f.sale_day):
            a["sold"] += f.qty
            a["net"] += f.gross
            if f.complete:
                a["net_c"] += f.gross
                a["profit"] += f.sale_profit or 0
                a["complete_any"] = True
            else:
                a["unknown"] = True
        for r in f.returns:
            if _in(period, r.day):
                a["returned"] += r.qty
                a["net"] -= r.refund
                if f.complete:
                    a["net_c"] -= r.refund
                    a["profit"] += r.delta or 0
                else:
                    a["unknown"] = True

    out: dict[str, ProductStats] = {}
    for pid, product in data.products.items():
        a = acc.get(pid)
        has_cost = bool(data.versions.get(pid))
        if a is None:
            out[pid] = ProductStats(product, has_cost, 0, 0, 0, None, None, False)
            continue
        complete = a["complete_any"]
        profit = a["profit"] if complete else None
        margin = round_half_up_div(a["profit"] * 10_000, a["net_c"]) if complete and a["net_c"] > 0 else None
        out[pid] = ProductStats(product, has_cost, a["sold"], a["returned"], a["net"], profit, margin,
                                complete and not a["unknown"])
    return out


def product_badges(stats: ProductStats) -> list[str]:
    badges: list[str] = []
    if not stats.has_cost:
        badges.append("no_cost")
    if stats.profit is not None and stats.profit < 0:
        badges.append("in_minus")
    if stats.sold_qty and stats.returned_qty >= 2 and stats.returned_qty * 10 >= stats.sold_qty:
        badges.append("many_returns")
    if stats.sold_qty == 0:
        badges.append("no_sales")
    return badges


# ---------- обзор ----------

def pct_bp(cur: int, prev: int) -> int | None:
    if prev == 0:
        return None
    return round_half_up_div((cur - prev) * 10_000, abs(prev))


def overview(data: ShopData, facts: list[ItemFact], period: Period, now: datetime) -> dict:
    cur = metrics_for(facts, data.orders, data.tz, period)
    prev_period = period.previous_equal()
    prev = metrics_for(facts, data.orders, data.tz, prev_period)
    stats = product_stats(data, facts, period)

    in_minus = [s for s in stats.values() if product_badges(s) and "in_minus" in product_badges(s)]
    no_cost = [s for s in data.products.values() if not data.versions.get(s.id)]
    many_returns = [s for s in stats.values() if "many_returns" in product_badges(s)]
    best = sorted([s for s in stats.values() if s.profit is not None], key=lambda s: -s.profit)[:3]

    days = [period.start + timedelta(days=i) for i in range(period.days)]
    prev_days = [prev_period.start + timedelta(days=i) for i in range(prev_period.days)]
    series = {
        "days": [d.isoformat() for d in days],
        "profit": [cur.day_profit.get(d, 0) for d in days],
        "sales": [cur.day_net.get(d, 0) for d in days],
        "prev_profit": [prev.day_profit.get(d, 0) for d in prev_days],
        "prev_sales": [prev.day_net.get(d, 0) for d in prev_days],
    }
    today_local = now.astimezone(data.tz).date()
    return {
        "shop_id": data.shop.id,
        "period": {"from": period.start.isoformat(), "to": period.end.isoformat()},
        "comparison_period": {"from": prev_period.start.isoformat(), "to": prev_period.end.isoformat()},
        "data_as_of": now.astimezone(timezone.utc).isoformat(),
        "is_today_in_period": period.contains(today_local),
        "kpi": {
            "net_sales_minor": cur.net_sales,
            "net_sales_delta_bp": pct_bp(cur.net_sales, prev.net_sales),
            "profit_minor": cur.profit,
            "profit_delta_bp": pct_bp(cur.profit, prev.profit),
            "coverage_bp": cur.coverage_bp,
            "orders_count": cur.orders_count,
            "orders_delta": cur.orders_count - prev.orders_count,
            "returns_cancels_count": cur.returns_count + cur.cancelled_count,
            "returns_cancels_delta": (cur.returns_count + cur.cancelled_count) - (prev.returns_count + prev.cancelled_count),
        },
        "attention": {
            "in_minus": [{"product_id": s.product.id, "sku": s.product.sku, "name": s.product.name,
                          "profit_minor": s.profit} for s in in_minus],
            "no_cost_count": len(no_cost),
            "many_returns": [{"product_id": s.product.id, "sku": s.product.sku, "name": s.product.name,
                              "returned_qty": s.returned_qty} for s in many_returns],
        },
        "best_products": [{"product_id": s.product.id, "sku": s.product.sku, "name": s.product.name,
                           "profit_minor": s.profit, "margin_bp": s.margin_bp} for s in best],
        "series": series,
    }


def profit_breakdown(data: ShopData, facts: list[ItemFact], period: Period) -> dict:
    m = metrics_for(facts, data.orders, data.tz, period)
    exp = expenses_in(data.expenses, period)
    landed_net = m.landed_c - m.recovered_c
    comm_net = m.commission_c - m.comm_returned_c
    del_net = m.delivery_c + m.extra_delivery_c
    tax_net = m.tax_c - m.tax_returned_c
    tax_applied = bool(m.tax_rates_seen) or m.tax_returned_c != 0
    store_profit = m.profit - exp["ads"] - exp["other"]
    missing = [
        {"product_id": s.product.id, "sku": s.product.sku, "name": s.product.name,
         "reason": "no_cost" if not s.has_cost else "incomplete"}
        for s in product_stats(data, facts, period).values()
        if s.sold_qty and not s.complete
    ]
    steps = [
        {"key": "net_sales", "minor": m.net_complete, "label": "Чистые продажи (полный набор)"},
        {"key": "cost", "minor": -landed_net, "label": "Себестоимость"},
        {"key": "commission", "minor": -comm_net, "label": "Комиссия"},
        {"key": "delivery", "minor": -del_net, "label": "Доставка покупателю"},
    ]
    if tax_applied:
        # Строка налога — только если ставка задана (ТЗ 2.1, раздел 7.2).
        rates = sorted(m.tax_rates_seen)
        label = f"Налог ({_pct_label(rates[0])}%)" if len(rates) == 1 else "Налог"
        steps.append({"key": "tax", "minor": -tax_net, "label": label, "rate_bp": rates[0] if len(rates) == 1 else None})
    steps += [
        {"key": "product_profit", "minor": m.profit, "label": "Прибыль по товарам"},
        {"key": "ads", "minor": -exp["ads"], "label": "Реклама"},
        {"key": "other_expenses", "minor": -exp["other"], "label": "Прочие расходы магазина"},
        {"key": "store_profit", "minor": store_profit, "label": "Прибыль магазина"},
    ]
    return {
        "period": {"from": period.start.isoformat(), "to": period.end.isoformat()},
        "steps": steps,
        "coverage_bp": m.coverage_bp,
        "net_sales_all_minor": m.net_sales,
        "missing": missing,
        "note": (
            "Расчётная прибыль после налога по вашей ставке. Не является бухгалтерской отчётностью."
            if tax_applied else "Расчётная прибыль до налогов. Не является бухгалтерской отчётностью."
        ),
    }


def _pct_label(bp: int) -> str:
    """Ставка в базисных пунктах → проценты для подписи: 400 → «4», 150 → «1,5»."""
    from decimal import Decimal

    text = format((Decimal(bp) / Decimal(100)).normalize(), "f")
    return text.replace(".", ",")


def orders_list(data: ShopData, period: Period, status: str | None, query: str | None,
                offset: int, limit: int) -> dict:
    rows = []
    q = (query or "").strip().lower()
    for o in reversed(data.orders):
        day = local_day(o.created_at, data.tz)
        if not period.contains(day):
            continue
        if status and not _status_match(o.status, status):
            continue
        names = " ".join(data.products[i.product_id].name.lower() for i in o.items if i.product_id in data.products)
        if q and q not in o.number and q not in names:
            continue
        rows.append(o)
    page = rows[offset: offset + limit]
    next_offset = offset + limit if offset + limit < len(rows) else None
    return {
        "items": [_order_summary(o, data) for o in page],
        "total": len(rows),
        "next_cursor": str(next_offset) if next_offset is not None else None,
    }


def _status_match(status: str, wanted: str) -> bool:
    groups = {
        "completed": {"completed"},
        "returns": {"returned", "partial_return"},
        "cancelled": {"cancelled"},
        "open": {"in_progress", "pending"},
    }
    return status in groups.get(wanted, {wanted})


def _order_summary(o: Order, data: ShopData) -> dict:
    names = [data.products[i.product_id].name for i in o.items if i.product_id in data.products]
    total = sum(i.unit_price_minor * i.qty for i in o.items)
    return {
        "id": o.id,
        "number": o.number,
        "status": o.status,
        "created_at": o.created_at.astimezone(data.tz).isoformat(),
        "items_count": sum(i.qty for i in o.items),
        "summary": f"{len(names)} тов. · {names[0]}" + (" …" if len(names) > 1 else "") if names else "",
        "total_minor": total,
    }


def order_detail(data: ShopData, facts: list[ItemFact], order: Order) -> dict:
    mine = [f for f in facts if f.order_id == order.id]
    items = []
    for f in mine:
        items.append({
            "product_id": f.product_id,
            "sku": f.sku,
            "name": f.name,
            "qty": f.qty,
            "unit_price_minor": f.unit_price,
            "gross_minor": f.gross,
            "commission_minor": f.commission,
            "commission_source": _rate_label(f.rate_source),
            # налог показываем только если ставка задана на дату заказа (ТЗ 2.1, раздел 7.2)
            "tax_minor": f.tax if f.tax_rate_bp is not None else None,
            "tax_rate_bp": f.tax_rate_bp,
            "landed_minor": f.landed,
            "cost_source": _cost_label(f.cost_source),
            "profit_minor": f.sale_profit,
            "returns": [{"day": r.day.isoformat(), "qty": r.qty, "refund_minor": r.refund,
                         "profit_delta_minor": r.delta} for r in f.returns],
        })
    return {
        "id": order.id,
        "number": order.number,
        "status": order.status,
        "created_at": order.created_at.astimezone(data.tz).isoformat(),
        "completed_at": order.completed_at.astimezone(data.tz).isoformat() if order.completed_at else None,
        "items": items,
    }


def _rate_label(source: str | None) -> str:
    return {"demo": "демо-ставка", "override": "вручную", "manual": "вручную"}.get(source or "", "нет ставки")


def _cost_label(source: str | None) -> str:
    return {"demo": "демо", "import": "импорт файла", "manual": "вручную"}.get(source or "", "нет закупки")


def products_list(data: ShopData, facts: list[ItemFact], period: Period, flt: str | None, sort: str,
                  query: str | None, offset: int, limit: int) -> dict:
    stats = product_stats(data, facts, period)
    rows = list(stats.values())
    q = (query or "").strip().lower()
    if q:
        rows = [s for s in rows if q in s.product.name.lower() or q in s.product.sku.lower()]
    if flt:
        def match(s: ProductStats) -> bool:
            b = product_badges(s)
            return {"in_minus": "in_minus" in b, "no_cost": "no_cost" in b,
                    "many_returns": "many_returns" in b, "no_sales": "no_sales" in b}.get(flt, True)
        rows = [s for s in rows if match(s)]
    keys = {
        "profit_desc": lambda s: (s.profit is None, -(s.profit or 0)),
        "profit_asc": lambda s: (s.profit is None, (s.profit or 0)),
        "sales": lambda s: -s.net_sales,
        "margin": lambda s: (s.margin_bp is None, -(s.margin_bp or 0)),
        "name": lambda s: s.product.name.lower(),
    }
    rows.sort(key=keys.get(sort, keys["profit_desc"]))
    page = rows[offset: offset + limit]
    next_offset = offset + limit if offset + limit < len(rows) else None
    complete_count = sum(1 for s in stats.values() if s.has_cost and s.complete)
    return {
        "items": [_product_row(s) for s in page],
        "total": len(rows),
        "coverage": {"complete": complete_count, "total": len(stats)},
        "next_cursor": str(next_offset) if next_offset is not None else None,
    }


def _product_row(s: ProductStats) -> dict:
    return {
        "product_id": s.product.id,
        "sku": s.product.sku,
        "name": s.product.name,
        "category": s.product.category,
        "sold_qty": s.sold_qty,
        "returned_qty": s.returned_qty,
        "net_sales_minor": s.net_sales,
        "profit_minor": s.profit,
        "margin_bp": s.margin_bp,
        "badges": product_badges(s),
    }


def product_detail(data: ShopData, facts: list[ItemFact], product: Product, period: Period, now: datetime) -> dict:
    stats = product_stats(data, facts, period)[product.id]
    versions = data.versions.get(product.id, [])
    current = active_cost(versions, now.astimezone(data.tz).date())
    mine = [f for f in facts if f.product_id == product.id and f.is_sale]
    sold_in = [f for f in mine if _in(period, f.sale_day)]
    per_day: dict[str, int] = defaultdict(int)
    for f in sold_in:
        per_day[f.sale_day.isoformat()] += f.qty
    days = [period.start + timedelta(days=i) for i in range(period.days)]

    econ = None
    done = [f for f in sold_in if f.complete]
    if done:
        units = sum(f.qty for f in done)
        econ = {
            "avg_price_minor": round_half_up_div(sum(f.gross for f in done), units),
            "landed_minor": round_half_up_div(sum(f.landed or 0 for f in done), units),
            "commission_bp": round_half_up_div(sum(f.commission or 0 for f in done) * 10_000,
                                               sum(f.gross for f in done)),
            "commission_minor": round_half_up_div(sum(f.commission or 0 for f in done), units),
            "delivery_minor": round_half_up_div(sum(f.delivery or 0 for f in done), units),
            "tax_minor": (round_half_up_div(sum(f.tax for f in done), units)
                          if any(f.tax_rate_bp is not None for f in done) else None),
            "profit_per_unit_minor": round_half_up_div(sum(f.sale_profit or 0 for f in done), units),
        }
    returns_hist = [
        {"day": r.day.isoformat(), "qty": r.qty, "refund_minor": r.refund, "known": r.known}
        for f in mine for r in f.returns
    ]
    return {
        "product": _product_row(stats),
        "period": {"from": period.start.isoformat(), "to": period.end.isoformat()},
        "daily_units": [{"day": d.isoformat(), "qty": per_day.get(d.isoformat(), 0)} for d in days],
        "economics": econ,
        "current_cost": None if current is None else {
            "purchase_minor": current.purchase_minor,
            "delivery_to_warehouse_minor": current.delivery_to_warehouse_minor,
            "packaging_minor": current.packaging_minor,
            "other_minor": current.other_minor,
            "effective_from": current.effective_from.isoformat() if current.effective_from else None,
            "source": _cost_label(current.source),
        },
        "cost_history": [
            {"id": v.id, "effective_from": v.effective_from.isoformat() if v.effective_from else None,
             "landed_unit_minor": v.landed_unit_minor, "source": _cost_label(v.source)}
            for v in versions
        ],
        "returns": returns_hist,
        "data_complete": stats.complete,
    }


def missing_costs(data: ShopData) -> list[dict]:
    return [
        {"product_id": p.id, "sku": p.sku, "name": p.name, "category": p.category}
        for p in sorted(data.products.values(), key=lambda p: p.sku)
        if not data.versions.get(p.id)
    ]


# ---------- для помощника: экспресс-аналитика по периодам ----------

@dataclass
class ProductPeriodFacts:
    product: Product
    sale_units: int
    profit: int | None  # прибыль полного набора в периоде (продажи + возвраты периода)
    sale_profit: int  # S: прибыль продаж (без возвратов), полный набор
    return_loss: int  # R: потери от возвратов (положительное число)
    price_u: Fraction
    cost_u: Fraction
    comm_u: Fraction
    del_u: Fraction
    tax_u: Fraction
    complete: bool


def comparable_facts(data: ShopData, facts: list[ItemFact], period: Period) -> dict[str, ProductPeriodFacts]:
    acc: dict[str, dict] = {}
    for f in facts:
        if not f.is_sale or not _in(period, f.sale_day) and not any(_in(period, r.day) for r in f.returns):
            continue
        a = acc.setdefault(f.product_id, {"units": 0, "S": 0, "R": 0, "gross": 0, "landed": 0, "comm": 0,
                                           "del": 0, "tax": 0, "ok": True, "product": data.products[f.product_id]})
        if _in(period, f.sale_day):
            a["units"] += f.qty
            if f.complete:
                a["S"] += f.sale_profit or 0
                a["gross"] += f.gross
                a["landed"] += f.landed or 0
                a["comm"] += f.commission or 0
                a["del"] += f.delivery or 0
                a["tax"] += f.tax
            else:
                a["ok"] = False
        for r in f.returns:
            if _in(period, r.day):
                if f.complete:
                    a["R"] -= r.delta or 0
                else:
                    a["ok"] = False
    out: dict[str, ProductPeriodFacts] = {}
    for pid, a in acc.items():
        units = a["units"]
        q = Fraction(units) if units else Fraction(0)
        out[pid] = ProductPeriodFacts(
            product=a["product"], sale_units=units,
            profit=(a["S"] - a["R"]) if a["ok"] else None,
            sale_profit=a["S"], return_loss=a["R"],
            price_u=Fraction(a["gross"], units) if units else Fraction(0),
            cost_u=Fraction(a["landed"], units) if units else Fraction(0),
            comm_u=Fraction(a["comm"], units) if units else Fraction(0),
            del_u=Fraction(a["del"], units) if units else Fraction(0),
            tax_u=Fraction(a["tax"], units) if units else Fraction(0),
            complete=a["ok"],
        )
    return out


def explain_profit_change(data: ShopData, facts: list[ItemFact], a: Period, b: Period) -> dict:
    """Разложение изменения прибыли между периодами A и B (docs/spec.md, раздел 8.4).

    Для товаров с полными данными в обоих периодах:
      объём = (qB − qA) × uA;  юнит-экономика = (uB − uA) × qB (цена, себестоимость, комиссия, доставка);
      возвраты = −(RB − RA).  Если qA = 0, принимаем uA = uB.
    Остаток округления выводится отдельной строкой, сумма эффектов точно равна изменению.
    """
    fa = comparable_facts(data, facts, a)
    fb = comparable_facts(data, facts, b)
    pids = set(fa) | set(fb)
    comparable: list[dict] = []
    outside_a = outside_b = 0
    contrib: dict[str, Fraction] = defaultdict(Fraction)
    comp_totals = {"volume": Fraction(0), "price": Fraction(0), "cost": Fraction(0),
                   "commission": Fraction(0), "delivery": Fraction(0), "tax": Fraction(0), "returns": Fraction(0)}
    for pid in pids:
        A = fa.get(pid)
        B = fb.get(pid)
        # Товар сопоставим, если данные полные во всех периодах, где он продавался (q = 0 допустим).
        okA = A is None or A.complete
        okB = B is None or B.complete
        if not (okA and okB):
            if A and A.profit is not None:
                outside_a += A.profit
            if B and B.profit is not None:
                outside_b += B.profit
            continue
        qA = Fraction(A.sale_units) if A else Fraction(0)
        qB = Fraction(B.sale_units) if B else Fraction(0)
        # Удельные компоненты: при q = 0 в периоде берём значения другого периода (u_A = u_B, раздел 8.4)
        comp_a = (A.price_u, A.cost_u, A.comm_u, A.del_u, A.tax_u) if qA else None
        comp_b = (B.price_u, B.cost_u, B.comm_u, B.del_u, B.tax_u) if qB else None
        comp_a = comp_a or comp_b or (Fraction(0),) * 5
        comp_b = comp_b or comp_a
        pA, cA, kA, dA, tA = comp_a
        pB, cB, kB, dB, tB = comp_b
        uA = pA - cA - kA - dA - tA
        volume = (qB - qA) * uA
        price_e = (pB - pA) * qB
        cost_e = -(cB - cA) * qB
        comm_e = -(kB - kA) * qB
        del_e = -(dB - dA) * qB
        tax_e = -(tB - tA) * qB
        ret_a = Fraction(A.return_loss) if A else Fraction(0)
        ret_b = Fraction(B.return_loss) if B else Fraction(0)
        returns_e = -(ret_b - ret_a)
        total = volume + price_e + cost_e + comm_e + del_e + tax_e + returns_e
        contrib[pid] = total
        comp_totals["volume"] += volume
        comp_totals["price"] += price_e
        comp_totals["cost"] += cost_e
        comp_totals["commission"] += comm_e
        comp_totals["delivery"] += del_e
        comp_totals["tax"] += tax_e
        comp_totals["returns"] += returns_e
        product = (A or B).product
        comparable.append({
            "product_id": pid, "sku": product.sku, "name": product.name,
            "effect_minor": _round_fraction(total),
            "volume_minor": _round_fraction(volume),
            "unit_minor": _round_fraction(price_e + cost_e + comm_e + del_e),
            "returns_minor": _round_fraction(returns_e),
            "profit_a_minor": A.profit if A else 0,
            "profit_b_minor": B.profit if B else 0,
            "units_a": A.sale_units if A else 0,
            "units_b": B.sale_units if B else 0,
        })

    m_a = metrics_for(facts, data.orders, data.tz, a)
    m_b = metrics_for(facts, data.orders, data.tz, b)
    expA = expenses_in(data.expenses, a)
    expB = expenses_in(data.expenses, b)
    store_exp_change = -((expB["ads"] + expB["other"]) - (expA["ads"] + expA["other"]))
    outside_change = outside_b - outside_a
    profit_a = m_a.profit - expA["ads"] - expA["other"]
    profit_b = m_b.profit - expB["ads"] - expB["other"]
    total_change = profit_b - profit_a

    rounded_sum = sum(_round_fraction(contrib[pid]) for pid in contrib) + outside_change + store_exp_change
    residual = total_change - rounded_sum

    comparable.sort(key=lambda r: -abs(r["effect_minor"]))
    top = comparable[0] if comparable else None
    top_share = None
    if top and total_change != 0:
        top_share = round_half_up_div(top["effect_minor"] * 10_000, total_change)
    return {
        "period_a": {"from": a.start.isoformat(), "to": a.end.isoformat()},
        "period_b": {"from": b.start.isoformat(), "to": b.end.isoformat()},
        "profit_a_minor": profit_a,
        "profit_b_minor": profit_b,
        "change_minor": total_change,
        "coverage_a_bp": m_a.coverage_bp,
        "coverage_b_bp": m_b.coverage_bp,
        "effects": {
            "volume_minor": _round_fraction(comp_totals["volume"]),
            "unit_economics_minor": _round_fraction(comp_totals["price"] + comp_totals["cost"]
                                                     + comp_totals["commission"] + comp_totals["delivery"]
                                                     + comp_totals["tax"]),
            "returns_minor": _round_fraction(comp_totals["returns"]),
            "outside_comparable_minor": outside_change,
            "store_expenses_minor": store_exp_change,
            "rounding_minor": residual,
        },
        "products": comparable,
        "top_driver": None if top is None else {"product_id": top["product_id"], "sku": top["sku"],
                                                "name": top["name"], "effect_minor": top["effect_minor"],
                                                "share_bp": top_share,
                                                "main_factor": "volume" if abs(top["volume_minor"]) >= abs(top["unit_minor"]) else "unit"},
        "coverage_comparable": all(r["profit_a_minor"] is not None for r in comparable),
    }


def _round_fraction(x: Fraction) -> int:
    n, d = x.numerator, x.denominator
    sign = -1 if n < 0 else 1
    return sign * ((abs(n) * 2 + d) // (2 * d))
