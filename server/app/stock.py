"""Склад (PROPOSALS 18, решения владельца 22.11): остаток = внесённый продавцом на момент внесения − продажи после него
+ возвраты годного товара после него. Расчёт по заказам, без фоновых задач. Пороги уведомлений: 10, 5, 3 шт. и 0."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from .models import Order, OrderItem, Product, ProductStock, ReturnEvent, Shop

CANCEL = {"cancelled"}
THRESHOLDS = (10, 5, 3)  # уведомления при понижении остатка до порога
SALE_WINDOW_DAYS = 14   # скорость продаж — среднее за 14 дней
ENDING_SOON_DAYS = 14   # «закончится через N дней» — в списке, если прогноз ≤ 14 дней


@dataclass
class StockState:
    product_id: str
    sku: str
    name: str
    base_qty: int
    base_at: datetime
    sold_since: int
    returned_since: int
    current: int
    avg_daily: float
    days_left: int | None
    level: str | None  # out | t3 | t5 | t10 | None
    delisted: bool


def _level(current: int) -> str | None:
    if current <= 0:
        return "out"
    for t in sorted(THRESHOLDS):
        if current <= t:
            return f"t{t}"
    return None


def stock_states(db: DbSession, shop: Shop, now: datetime | None = None) -> dict[str, StockState]:
    now = now or datetime.now(timezone.utc)
    rows = db.scalars(select(ProductStock).where(ProductStock.shop_id == shop.id)).all()
    out: dict[str, StockState] = {}
    if not rows:
        return out
    products = {p.id: p for p in db.scalars(select(Product).where(Product.shop_id == shop.id)).all()}
    items = db.execute(
        select(OrderItem.product_id, OrderItem.qty, Order.created_at, Order.status)
        .join(Order, Order.id == OrderItem.order_id)
        .where(OrderItem.shop_id == shop.id)
    ).all()
    returns = db.execute(
        select(OrderItem.product_id, ReturnEvent.returned_qty, ReturnEvent.confirmed_at, ReturnEvent.goods_sellable)
        .join(OrderItem, OrderItem.id == ReturnEvent.item_id)
        .where(ReturnEvent.shop_id == shop.id)
    ).all()
    recent_cut = now - timedelta(days=SALE_WINDOW_DAYS)
    for r in rows:
        p = products.get(r.product_id)
        if p is None:
            continue
        base = r.updated_at if r.updated_at.tzinfo else r.updated_at.replace(tzinfo=timezone.utc)
        sold = sum(q for pid, q, created, status in items
                   if pid == r.product_id and status not in CANCEL and _aware(created) >= base)
        returned = sum(q for pid, q, confirmed, sellable in returns
                       if pid == r.product_id and sellable and _aware(confirmed) >= base)
        current = r.qty - sold + returned
        recent = sum(q for pid, q, created, status in items
                     if pid == r.product_id and status not in CANCEL and _aware(created) >= recent_cut)
        avg = recent / SALE_WINDOW_DAYS
        days = int(current / avg) if avg > 0 and current > 0 else (0 if current <= 0 else None)
        out[r.product_id] = StockState(r.product_id, p.sku, p.name, r.qty, base, sold, returned, current,
                                       round(avg, 2), days, _level(current), bool(r.delisted))
    return out


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


LEVEL_TEXT = {"out": "закончился", "t3": "осталось 3 шт. или меньше", "t5": "осталось 5 шт. или меньше",
              "t10": "осталось 10 шт. или меньше"}


def stock_push_mock(shop: Shop, st: StockState) -> None:
    """Push на моке: файл в outbox/push (без персональных данных: только название товара и остаток)."""
    import json
    from .config import settings
    folder = settings.outbox_dir / "push"
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
    payload = {"shopId": shop.id, "productId": st.product_id, "title": "Склад: " + st.name,
               "body": f"Остаток: {st.current} шт. — {LEVEL_TEXT.get(st.level or '', '')}.", "level": st.level}
    (folder / f"{stamp}_{st.product_id}.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
