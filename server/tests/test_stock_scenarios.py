"""Склад: проверка пересчёта остатков по сценариям (К-1, пункт 2, 22.11).
Верное поведение: остаток = последняя инвентаризация + приходы после неё − продажи после неё + годные возвраты после неё.
Приход задним числом учитывается по дате прихода, а не по дате ввода."""

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.db import engine
from app.models import Order, OrderItem, Product, ReturnEvent, Shop
from app.stock import stock_states
from app.timeutil import utc_now


def _product(shop_id):
    with DbSession(engine) as db:
        return db.scalars(select(Product).where(Product.shop_id == shop_id).order_by(Product.sku)).first().id


def _order(shop_id, pid, qty, created, status="completed", number=None):
    with DbSession(engine) as db:
        o = Order(shop_id=shop_id, number=number or f"SC-{utc_now().timestamp()}-{qty}", status=status,
                  created_at=created, completed_at=created)
        db.add(o)
        db.flush()
        it = OrderItem(order_id=o.id, shop_id=shop_id, product_id=pid, qty=qty, unit_price_minor=100000)
        db.add(it)
        db.commit()
        return o.id, it.id


def _current(shop_id, pid):
    with DbSession(engine) as db:
        st = stock_states(db, db.get(Shop, shop_id))
        return st[pid].current if pid in st else None


def _inventory(client, demo, pid, qty, when=None):
    """Инвентаризация через API (ставит «сейчас»), затем дата пересчёта переносится в when (по умолчанию — 30 дней назад)."""
    r = client.put(f"/v1/shops/{demo['shop_id']}/products/{pid}/stock", headers=demo["headers"], json={"qty": qty})
    assert r.status_code == 200, r.text
    from app.models import StockMovement
    with DbSession(engine) as db:
        mv = db.scalars(select(StockMovement).where(StockMovement.product_id == pid, StockMovement.kind == "inventory")
                        .order_by(StockMovement.created_at.desc())).first()
        mv.occurred_at = when or (utc_now() - timedelta(days=30))
        db.commit()


def _receipt(client, demo, pid, qty, occurred_at=None):
    body = {"qty": qty}
    if occurred_at is not None:
        body["occurred_at"] = occurred_at.isoformat()
    r = client.post(f"/v1/shops/{demo['shop_id']}/products/{pid}/stock/receipt", headers=demo["headers"], json=body)
    assert r.status_code == 200, r.text


def _clean_orders(shop_id):
    with DbSession(engine) as db:
        db.query(OrderItem).filter(OrderItem.shop_id == shop_id).delete()
        db.query(Order).filter(Order.shop_id == shop_id).delete()
        db.commit()


def test_order_qty_edit_is_reflected(client, demo):
    shop = demo["shop_id"]
    pid = _product(shop)
    _clean_orders(shop)
    now = utc_now()
    _inventory(client, demo, pid, 10)
    _, item_id = _order(shop, pid, 2, now - timedelta(minutes=5))
    assert _current(shop, pid) == 8
    with DbSession(engine) as db:
        db.get(OrderItem, item_id).qty = 5  # правка заказа: 2 → 5
        db.commit()
    assert _current(shop, pid) == 5


def test_partial_return_adds_only_sellable_goods(client, demo):
    shop = demo["shop_id"]
    pid = _product(shop)
    _clean_orders(shop)
    now = utc_now()
    _inventory(client, demo, pid, 10)
    _, item_id = _order(shop, pid, 5, now - timedelta(minutes=5))
    with DbSession(engine) as db:
        db.add(ReturnEvent(item_id=item_id, shop_id=shop, returned_qty=2, confirmed_at=now, goods_sellable=True))
        db.add(ReturnEvent(item_id=item_id, shop_id=shop, returned_qty=1, confirmed_at=now, goods_sellable=False))
        db.commit()
    # 10 − 5 + 2 (годные) = 7; негодные 1 не возвращаются
    assert _current(shop, pid) == 7


def test_deleting_an_order_returns_its_quantity(client, demo):
    shop = demo["shop_id"]
    pid = _product(shop)
    _clean_orders(shop)
    now = utc_now()
    _inventory(client, demo, pid, 10)
    oid, _ = _order(shop, pid, 3, now - timedelta(minutes=5))
    assert _current(shop, pid) == 7
    with DbSession(engine) as db:
        db.delete(db.get(Order, oid))
        db.commit()
    assert _current(shop, pid) == 10


def test_repeated_inventory_resets_base_and_ignores_older_sales(client, demo):
    shop = demo["shop_id"]
    pid = _product(shop)
    _clean_orders(shop)
    now = utc_now()
    _inventory(client, demo, pid, 10)
    _order(shop, pid, 4, now - timedelta(days=2))
    _inventory(client, demo, pid, 6, when=now - timedelta(days=1))  # пересчёт вчера: 6 штук на полке
    assert _current(shop, pid) == 6  # продажа 2 дня назад уже учтена в пересчитанных 6
    _order(shop, pid, 1, now - timedelta(minutes=1))
    assert _current(shop, pid) == 5


def test_receipt_dated_before_last_inventory_is_not_added_twice(client, demo):
    """Приход задним числом, который был до пересчёта, уже учтён в пересчитанном остатке."""
    shop = demo["shop_id"]
    pid = _product(shop)
    _clean_orders(shop)
    now = utc_now()
    _inventory(client, demo, pid, 10, when=now - timedelta(days=2))  # пересчёт 2 дня назад
    assert _current(shop, pid) == 10
    # приход 5 штук, но датированный 5 днями назад — раньше пересчёта «сейчас»: в остаток не входит
    _receipt(client, demo, pid, 5, occurred_at=now - timedelta(days=5))
    assert _current(shop, pid) == 10


def test_receipt_dated_after_inventory_is_added(client, demo):
    shop = demo["shop_id"]
    pid = _product(shop)
    _clean_orders(shop)
    now = utc_now()
    _inventory(client, demo, pid, 10)
    _receipt(client, demo, pid, 5, occurred_at=now - timedelta(minutes=1))
    assert _current(shop, pid) == 15


def test_receipt_without_inventory_is_refused(client, demo):
    shop = demo["shop_id"]
    pid = _product(shop)
    from app.models import ProductStock, StockMovement
    with DbSession(engine) as db:
        db.query(ProductStock).filter(ProductStock.product_id == pid).delete()
        db.query(StockMovement).filter_by(product_id=pid).delete()
        db.commit()
    r = client.post(f"/v1/shops/{shop}/products/{pid}/stock/receipt", headers=demo["headers"], json={"qty": 3})
    assert r.status_code == 409


def test_receipt_from_the_future_is_refused(client, demo):
    shop = demo["shop_id"]
    pid = _product(shop)
    _inventory(client, demo, pid, 10)
    future = utc_now() + timedelta(days=2)
    r = client.post(f"/v1/shops/{shop}/products/{pid}/stock/receipt", headers=demo["headers"],
                    json={"qty": 3, "occurred_at": future.isoformat()})
    assert r.status_code == 422
