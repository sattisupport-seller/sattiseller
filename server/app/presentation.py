"""Режим презентации (К-33, А3): пример остатков и себестоимости на товарах и продажах самого продавца.

Включает только владелец в админке для конкретного аккаунта. У обычных продавцов всё как в К-24: остаток вводится
вместе с себестоимостью.

- Пример остатков: запас примерно на 30 дней продаж; у нескольких самых продаваемых товаров — 0–1 шт.,
  чтобы показать автоснятие. Пишется как инвентаризация с пометкой example=True.
- Пример себестоимости: одно число «≈ N % от цены» (по умолчанию 60 %), меняется прямо на встрече.
  Пишется как версия затрат source="example".
- Свои цифры продавца всегда главнее: пример ставится только товарам без своих остатков / затрат, а более поздняя
  запись продавца перекрывает пример (последняя инвентаризация и последняя версия затрат).
- В его магазине Kaspi ничего не меняется: прайс-лист в режиме презентации не отдаётся (api.kaspi_price_list),
  автоснятие — только предпросмотр.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session as DbSession

from . import reportcache
from .models import Order, OrderItem, Product, ProductCostVersion, ProductStock, Shop, StockMovement

STOCK_DAYS = 30  # пример остатка — запас примерно на 30 дней продаж
PRICE_DAYS = 90  # средняя цена — по продажам за 90 дней
NO_SALES_STOCK = 5  # товар без продаж за 30 дней — небольшой пример остатка
LOW_STOCK_PRODUCTS = 3  # сколько самых продаваемых товаров получат остаток 0–1 (показать автоснятие)
DEFAULT_COST_PCT = 60
MIN_COST_PCT, MAX_COST_PCT = 1, 95
EXAMPLE = "example"


def _sales(db: DbSession, shop_id: str, now: datetime) -> tuple[dict[str, int], dict[str, int]]:
    """Продано штук за 30 дней и средняя цена единицы за 90 дней (тиыны) по товарам. Отмены не считаются."""
    since = now - timedelta(days=PRICE_DAYS)
    sold30: dict[str, int] = defaultdict(int)
    money: dict[str, int] = defaultdict(int)
    units: dict[str, int] = defaultdict(int)
    rows = db.execute(
        select(OrderItem.product_id, OrderItem.qty, OrderItem.unit_price_minor, Order.created_at)
        .join(Order, Order.id == OrderItem.order_id)
        .where(OrderItem.shop_id == shop_id, Order.status != "cancelled", Order.created_at >= since)
    ).all()
    cut30 = now - timedelta(days=STOCK_DAYS)
    for pid, qty, price, created in rows:
        created = created if created.tzinfo else created.replace(tzinfo=now.tzinfo)
        money[pid] += price * qty
        units[pid] += qty
        if created >= cut30:
            sold30[pid] += qty
    avg_price = {pid: money[pid] // units[pid] for pid in units if units[pid] > 0}
    return dict(sold30), avg_price


def _example_cost(avg_price_minor: int, pct: int) -> int:
    """Себестоимость-пример: pct % от средней цены, округлено до целого тенге."""
    return (avg_price_minor * pct + 5_000) // 10_000 * 100


def apply_examples(db: DbSession, shop: Shop, now: datetime) -> dict:
    """Ставит пример остатков и себестоимости товарам, у которых нет своих цифр продавца. Повторный вызов
    пересоздаёт примеры (старые удаляются), свои цифры продавца не трогает."""
    clear_examples(db, shop)
    products = db.scalars(select(Product).where(Product.shop_id == shop.id)).all()
    own_cost = set(db.scalars(select(ProductCostVersion.product_id).where(
        ProductCostVersion.shop_id == shop.id, ProductCostVersion.cancelled.is_(False))).all())
    own_stock = set(db.scalars(select(StockMovement.product_id).where(StockMovement.shop_id == shop.id)).all())
    own_stock |= set(db.scalars(select(ProductStock.product_id).where(ProductStock.shop_id == shop.id)).all())
    sold30, avg_price = _sales(db, shop.id, now)

    stock_targets = [p for p in products if p.id not in own_stock]
    top = sorted((p for p in stock_targets if sold30.get(p.id, 0) > 0), key=lambda p: (-sold30[p.id], p.sku))
    low = {p.id: i % 2 for i, p in enumerate(top[:LOW_STOCK_PRODUCTS])}  # 0, 1, 0 шт.
    stock_n = 0
    for p in stock_targets:
        qty = low.get(p.id)
        if qty is None:
            qty = sold30.get(p.id, 0) or NO_SALES_STOCK  # ≈ 30 дней продаж
        db.add(StockMovement(shop_id=shop.id, product_id=p.id, kind="inventory", qty=qty, occurred_at=now,
                             example=True))
        stock_n += 1

    cost_n = 0
    pct = shop.example_cost_pct or DEFAULT_COST_PCT
    for p in products:
        if p.id in own_cost or p.id not in avg_price:
            continue  # свои затраты продавца или цена неизвестна (нет продаж за 90 дней)
        db.add(ProductCostVersion(shop_id=shop.id, product_id=p.id, purchase_minor=_example_cost(avg_price[p.id], pct),
                                  effective_from=None, source=EXAMPLE))
        cost_n += 1
    db.flush()
    reportcache.invalidate(shop.id)
    return {"stock_examples": stock_n, "cost_examples": cost_n, "low_stock_products": len(low), "cost_pct": pct}


def set_cost_pct(db: DbSession, shop: Shop, pct: int, now: datetime) -> dict:
    """«≈ N % от цены» — меняется прямо на встрече: пересчитывает только примеры."""
    if not MIN_COST_PCT <= pct <= MAX_COST_PCT:
        raise ValueError(f"процент от {MIN_COST_PCT} до {MAX_COST_PCT}")
    shop.example_cost_pct = pct
    _sold30, avg_price = _sales(db, shop.id, now)
    n = 0
    for v in db.scalars(select(ProductCostVersion).where(ProductCostVersion.shop_id == shop.id,
                                                         ProductCostVersion.source == EXAMPLE)).all():
        if v.product_id in avg_price:
            v.purchase_minor = _example_cost(avg_price[v.product_id], pct)
            n += 1
    db.flush()
    reportcache.invalidate(shop.id)
    return {"cost_pct": pct, "cost_examples": n}


def clear_examples(db: DbSession, shop: Shop) -> None:
    """Убирает все примеры (выключение режима). Цифры продавца остаются."""
    db.execute(delete(ProductCostVersion).where(ProductCostVersion.shop_id == shop.id,
                                                ProductCostVersion.source == EXAMPLE))
    db.execute(delete(StockMovement).where(StockMovement.shop_id == shop.id, StockMovement.example.is_(True)))
    db.flush()
    reportcache.invalidate(shop.id)


def example_product_ids(db: DbSession, shop_id: str) -> tuple[set[str], set[str]]:
    """Товары, у которых сейчас действует пример: (остаток, себестоимость). Пример действует, если после него
    продавец не ввёл своих цифр."""
    stock_ex: set[str] = set()
    last_move: dict[str, bool] = {}
    for m in db.scalars(select(StockMovement).where(StockMovement.shop_id == shop_id, StockMovement.kind == "inventory")
                        .order_by(StockMovement.occurred_at, StockMovement.created_at)).all():
        last_move[m.product_id] = bool(m.example)
    stock_ex = {pid for pid, ex in last_move.items() if ex}
    last_cost: dict[str, str] = {}
    for v in db.scalars(select(ProductCostVersion).where(ProductCostVersion.shop_id == shop_id,
                                                         ProductCostVersion.cancelled.is_(False))
                        .order_by(ProductCostVersion.created_at)).all():
        last_cost[v.product_id] = v.source
    cost_ex = {pid for pid, src in last_cost.items() if src == EXAMPLE}
    return stock_ex, cost_ex


def drop_product_examples(db: DbSession, shop_id: str, product_id: str, *, stock: bool = False,
                          cost: bool = False) -> None:
    """Продавец вводит свои цифры — пример по этому товару убираем. Иначе своя себестоимость легла бы «с сегодня»
    поверх примера, а пример остатка с датой «сейчас» перекрыл бы инвентаризацию задним числом."""
    if stock:
        db.execute(delete(StockMovement).where(StockMovement.shop_id == shop_id, StockMovement.product_id == product_id,
                                               StockMovement.example.is_(True)))
    if cost:
        db.execute(delete(ProductCostVersion).where(ProductCostVersion.shop_id == shop_id,
                                                    ProductCostVersion.product_id == product_id,
                                                    ProductCostVersion.source == EXAMPLE))
    db.flush()
