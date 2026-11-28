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
    pending_returns: int = 0  # К-26: вернулось, но годность не подтверждена — остаток не увеличен
    returning: int = 0  # К-33 А4: отмена после передачи в Kaspi Доставку — едет обратно, ждёт «забрал»
    buffer: int = 0  # К-33 А4: буфер автоснятия
    example: bool = False  # К-33 А3: остаток — пример

    @property
    def for_sale(self) -> int:
        """Сколько показать в прайсе Kaspi: остаток минус буфер, не меньше 0."""
        return max(self.current - self.buffer, 0)


def _level(current: int) -> str | None:
    if current <= 0:
        return "out"
    for t in sorted(THRESHOLDS):
        if current <= t:
            return f"t{t}"
    return None


def stock_states(db: DbSession, shop: Shop, now: datetime | None = None) -> dict[str, StockState]:
    """Текущий остаток по товарам (К-1 от 22.11, журнал движений).
    База — последняя инвентаризация по дате события (журнал `stock_movements`); если её нет — старая запись `product_stocks`.
    Остаток = база + приходы с датой позже базы − продажи с даты базы (кроме отмен) + годные возвраты с даты базы.
    Дата ввода прихода значения не имеет: важна дата события."""
    from .models import StockMovement
    now = now or datetime.now(timezone.utc)
    products = {p.id: p for p in db.scalars(select(Product).where(Product.shop_id == shop.id)).all()}
    legacy = {r.product_id: r for r in db.scalars(select(ProductStock).where(ProductStock.shop_id == shop.id)).all()}
    moves = db.scalars(select(StockMovement).where(StockMovement.shop_id == shop.id)
                       .order_by(StockMovement.occurred_at)).all()
    # база по товару: последняя инвентаризация; иначе — старая запись
    base: dict[str, tuple[int, datetime]] = {}
    for m in moves:
        if m.kind == "inventory":
            base[m.product_id] = (m.qty, _aware(m.occurred_at))
    for pid, row in legacy.items():
        if pid not in base:
            base[pid] = (row.qty, _aware(row.updated_at))
    if not base:
        return {}
    items = db.execute(
        select(OrderItem.product_id, OrderItem.qty, Order.created_at, Order.status, Order.in_delivery_at)
        .join(Order, Order.id == OrderItem.order_id)
        .where(OrderItem.shop_id == shop.id)
    ).all()
    returns = db.execute(
        select(OrderItem.product_id, ReturnEvent.returned_qty, ReturnEvent.confirmed_at, ReturnEvent.goods_sellable)
        .join(OrderItem, OrderItem.id == ReturnEvent.item_id)
        .where(ReturnEvent.shop_id == shop.id)
    ).all()
    recent_cut = now - timedelta(days=SALE_WINDOW_DAYS)
    out: dict[str, StockState] = {}
    for pid, (base_qty, base_at) in base.items():
        p = products.get(pid)
        if p is None:
            continue
        receipts = sum(m.qty for m in moves if m.kind == "receipt" and m.product_id == pid
                       and _aware(m.occurred_at) > base_at)
        sold = sum(q for ipid, q, created, status, _hd in items
                   if ipid == pid and status not in CANCEL and _aware(created) >= base_at)
        # К-33 А4: отмена после передачи в Kaspi Доставку — товар не на складе, пока продавец не забрал его
        transit = sum(q for ipid, q, created, status, handed in items
                      if ipid == pid and status in CANCEL and handed is not None and _aware(created) >= base_at)
        transit += sum(m.qty for m in moves if m.kind == "cancel_transit" and m.product_id == pid
                       and _aware(m.occurred_at) >= base_at)
        back_ok = sum(m.qty for m in moves if m.kind == "back_ok" and m.product_id == pid
                      and _aware(m.occurred_at) >= base_at)
        back_defect = sum(m.qty for m in moves if m.kind == "back_defect" and m.product_id == pid
                          and _aware(m.occurred_at) >= base_at)
        returning = max(transit - back_ok - back_defect, 0)
        # частичные отмены Kaspi (движение «cancel»): позиция уже уменьшена, поэтому остаток не меняем дважды;
        # в «продано всего» отменённые штуки возвращаем, чтобы продажи были видны как было заказано
        cancelled = sum(m.qty for m in moves if m.kind in ("cancel", "cancel_transit") and m.product_id == pid
                        and _aware(m.occurred_at) >= base_at)
        sold_gross = sold + cancelled
        returned = sum(q for rpid, q, confirmed, sellable in returns
                       if rpid == pid and sellable and _aware(confirmed) >= base_at)
        pending = sum(q for rpid, q, confirmed, sellable in returns
                      if rpid == pid and sellable is None and _aware(confirmed) >= base_at)
        current = base_qty + receipts - sold - transit + back_ok + returned
        recent = sum(q for ipid, q, created, status, _hd in items
                     if ipid == pid and status not in CANCEL and _aware(created) >= recent_cut)
        avg = recent / SALE_WINDOW_DAYS
        days = int(current / avg) if avg > 0 and current > 0 else (0 if current <= 0 else None)
        row = legacy.get(pid)
        out[pid] = StockState(pid, p.sku, p.name, base_qty, base_at, sold_gross, returned, current,
                              round(avg, 2), days, _level(current), bool(row.delisted) if row else False, pending,
                              returning=returning, buffer=(row.buffer or 0) if row else 0)
    return out


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


LEVEL_TEXT = {"out": "закончился", "t3": "осталось 3 шт. или меньше", "t5": "осталось 5 шт. или меньше",
              "t10": "осталось 10 шт. или меньше"}


def stock_push_mock(shop: Shop, st: StockState) -> None:
    """Уведомление склада (3.4): через общую очередь пушей; тихие часы и деактивация учитываются там.
    Без персональных данных: только название товара и остаток."""
    from .db import SessionLocal
    from .push import enqueue

    with SessionLocal() as db:
        enqueue(db, shop.owner_user_id, "stock", "Склад: " + st.name,
                f"Остаток: {st.current} шт. — {LEVEL_TEXT.get(st.level or '', '')}.",
                {"screen": "stock", "productId": st.product_id, "level": st.level},
                dedup_key=f"stock:{st.product_id}:{st.level}:{datetime.now(timezone.utc):%Y%m%d%H%M}")
        db.commit()
