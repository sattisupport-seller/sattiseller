"""Склад по заказам Kaspi (решение владельца 22.11): заказ — минус, отмена или возврат — плюс,
повторная синхронизация не списывает дважды. Проверка на моке Kaspi, без реального токена."""

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from app.db import engine
from app.models import Order, OrderItem, Product, ProductStock, ReturnEvent
from tests.test_kaspi import _connect, kaspi_on, mock  # noqa: F401  (фикстуры)


def _sku_product(shop_id, sku):
    with DbSession(engine) as db:
        return db.scalar(select(Product).where(Product.shop_id == shop_id, Product.sku == sku))


def _expected_current(shop_id, pid, base_qty, base_at):
    """Независимый подсчёт по таблицам: минус продажи (кроме отмен) и плюс возвраты годного товара после базы."""
    with DbSession(engine) as db:
        sold = db.scalar(select(func.coalesce(func.sum(OrderItem.qty), 0)).join(Order, Order.id == OrderItem.order_id)
                         .where(OrderItem.product_id == pid, Order.status != "cancelled", Order.created_at >= base_at)) or 0
        ret = db.scalar(select(func.coalesce(func.sum(ReturnEvent.returned_qty), 0)).join(OrderItem, OrderItem.id == ReturnEvent.item_id)
                        .where(OrderItem.product_id == pid, ReturnEvent.goods_sellable.is_(True),
                               ReturnEvent.confirmed_at >= base_at)) or 0
        return base_qty - sold + ret


def test_kaspi_sync_deducts_sales_and_repeat_sync_does_not_double_count(client, demo, kaspi_on, mock):  # noqa: F811
    shop = demo["shop_id"]
    _connect(client, demo)
    now = datetime.now(timezone.utc)
    mock.generate(40, now=now, products=1)  # все заказы — товар K0
    assert client.post(f"/v1/shops/{shop}/kaspi/sync", headers=demo["headers"]).status_code == 200
    pid = _sku_product(shop, "K0").id
    base_at = now - timedelta(days=70)
    with DbSession(engine) as db:
        db.add(ProductStock(shop_id=shop, product_id=pid, qty=200, updated_at=base_at))
        db.commit()
    got = client.get(f"/v1/shops/{shop}/products/{pid}/stock", headers=demo["headers"]).json()
    assert got["current"] == _expected_current(shop, pid, 200, base_at)
    assert got["current"] < 200  # заказы списали остаток
    # повторная синхронизация: ничего не списывается дважды
    client.post(f"/v1/shops/{shop}/kaspi/sync", headers=demo["headers"])
    again = client.get(f"/v1/shops/{shop}/products/{pid}/stock", headers=demo["headers"]).json()
    assert again["current"] == got["current"]


def test_cancelled_order_in_kaspi_returns_stock_once(client, demo, kaspi_on, mock):  # noqa: F811
    shop = demo["shop_id"]
    _connect(client, demo)
    now = datetime.now(timezone.utc)
    mock.generate(10, now=now, products=1, state_cycle=["NEW"])  # все новые — списаны
    client.post(f"/v1/shops/{shop}/kaspi/sync", headers=demo["headers"])
    pid = _sku_product(shop, "K0").id
    base_at = now - timedelta(days=70)
    with DbSession(engine) as db:
        db.add(ProductStock(shop_id=shop, product_id=pid, qty=100, updated_at=base_at))
        db.commit()
    before = client.get(f"/v1/shops/{shop}/products/{pid}/stock", headers=demo["headers"]).json()["current"]
    mock.set_state("KC00000009", "CANCELLED")  # отмена в Kaspi
    client.post(f"/v1/shops/{shop}/kaspi/sync", headers=demo["headers"])
    after = client.get(f"/v1/shops/{shop}/products/{pid}/stock", headers=demo["headers"]).json()["current"]
    with DbSession(engine) as db:
        qty = db.scalar(select(func.coalesce(func.sum(OrderItem.qty), 0)).join(Order, Order.id == OrderItem.order_id)
                        .where(Order.number == "KC00000009", OrderItem.product_id == pid)) or 0
    assert after == before + qty
    client.post(f"/v1/shops/{shop}/kaspi/sync", headers=demo["headers"])  # повтор не возвращает дважды
    assert client.get(f"/v1/shops/{shop}/products/{pid}/stock", headers=demo["headers"]).json()["current"] == after
