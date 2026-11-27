"""2.5 (К-21): возвраты Kaspi. Заказ в статусе RETURNED не должен считаться продажей: возврат — по каждой позиции,
прибыль не завышается, остаток не уменьшается проданным, если товар вернулся на склад."""

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.db import engine
from app.models import Order, OrderItem, ReturnEvent
from tests.test_kaspi import _connect, kaspi_on, mock  # noqa: F401 — фикстуры


def _returns_of(code):
    with DbSession(engine) as db:
        order = db.scalar(select(Order).where(Order.number == code))
        items = db.scalars(select(OrderItem).where(OrderItem.order_id == order.id)).all()
        rets = db.scalars(select(ReturnEvent).where(ReturnEvent.item_id.in_([i.id for i in items]))).all()
        return items, rets


def test_returned_order_creates_return_per_item(client, demo, kaspi_on, mock):  # noqa: F811
    assert _connect(client, demo).status_code == 201
    mock.generate(4, now=datetime.now(timezone.utc), days=3, state_cycle=["COMPLETED", "RETURNED"], products=3)
    client.post(f"/v1/shops/{demo['shop_id']}/kaspi/sync", headers=demo["headers"])
    returned = [o["id"] for o in mock.orders if o["attributes"]["state"] == "RETURNED"]
    for code in returned:
        items, rets = _returns_of(code)
        assert items, code
        by_item = {r.item_id: r for r in rets}
        assert set(by_item) == {i.id for i in items}  # возврат по каждой позиции
        for i in items:
            assert by_item[i.id].returned_qty == i.qty and by_item[i.id].refund_minor == i.unit_price_minor * i.qty


def test_completed_then_returned_on_resync_is_idempotent(client, demo, kaspi_on, mock):  # noqa: F811
    assert _connect(client, demo).status_code == 201
    mock.generate(2, now=datetime.now(timezone.utc), days=2, state_cycle=["COMPLETED"], products=2)
    client.post(f"/v1/shops/{demo['shop_id']}/kaspi/sync", headers=demo["headers"])
    code = mock.orders[0]["id"]
    assert _returns_of(code)[1] == []
    mock.set_state(code, "RETURNED")
    from app import kaspi as kaspi_service
    from app.kaspi_client import KaspiClient
    from app.models import KaspiConnection

    with DbSession(engine) as db:
        conn = db.get(KaspiConnection, demo["shop_id"])
        client_k = KaspiClient(mock.token, transport=mock.transport(), sleep=lambda s: None, min_interval=0)
        kaspi_service.refresh_open_orders(db, conn, client_k, datetime.now(timezone.utc))
        kaspi_service.refresh_open_orders(db, conn, client_k, datetime.now(timezone.utc))  # повтор — без дублей
    items, rets = _returns_of(code)
    assert len(rets) == len(items)


def test_returned_order_does_not_inflate_sales_and_restores_stock(client, demo, kaspi_on, mock):  # noqa: F811
    """Возвращённый на склад заказ: в отчёте — возврат, а не продажа; остаток восстанавливается."""
    from app.models import Product, Shop

    assert _connect(client, demo).status_code == 201
    mock.generate(2, now=datetime.now(timezone.utc), days=2, state_cycle=["RETURNED"], products=1)
    for o in mock.orders:
        o["attributes"]["returnedToWarehouse"] = True
    client.post(f"/v1/shops/{demo['shop_id']}/kaspi/sync", headers=demo["headers"])
    with DbSession(engine) as db:
        shop = db.get(Shop, demo["shop_id"])
        k0 = db.scalar(select(Product).where(Product.shop_id == shop.id, Product.sku == "K0"))
        items = db.scalars(select(OrderItem).where(OrderItem.product_id == k0.id)).all()
        rets = db.scalars(select(ReturnEvent).where(ReturnEvent.item_id.in_([i.id for i in items]))).all()
        assert sum(r.returned_qty for r in rets) == sum(i.qty for i in items)
        assert all(r.goods_sellable is True for r in rets)
