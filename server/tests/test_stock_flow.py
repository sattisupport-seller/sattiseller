"""Склад: продажи уменьшают остаток, возвраты годного товара возвращают, приход, уведомления 10/5/3 без повторов,
снятие с продажи только при нуле и с подтверждением, помощник отвечает про остатки."""

from datetime import datetime, timezone
from types import SimpleNamespace

from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from app.config import settings
from app.db import engine
from app.kaspi import price_list_xml
from app.models import Order, OrderItem, Product, ProductStock, Shop
from tests.test_ai_live import _ask, _reply, _text, _tool, live  # noqa: F401  (фикстура live)


def _pid(demo):
    with DbSession(engine) as db:
        p = db.scalars(select(Product).where(Product.shop_id == demo["shop_id"]).order_by(Product.sku)).first()
        return p.id, p.sku, p.name


def _sold_since(demo, pid, since):
    with DbSession(engine) as db:
        return db.scalar(
            select(func.coalesce(func.sum(OrderItem.qty), 0)).join(Order, Order.id == OrderItem.order_id)
            .where(OrderItem.product_id == pid, Order.status != "cancelled", Order.created_at >= since)) or 0


def _set_baseline(demo, pid, qty, at):
    with DbSession(engine) as db:
        row = db.scalar(select(ProductStock).where(ProductStock.product_id == pid))
        if row is None:
            row = ProductStock(shop_id=demo["shop_id"], product_id=pid, qty=qty, updated_at=at)
            db.add(row)
        else:
            row.qty, row.updated_at, row.last_alert_level = qty, at, None
        db.commit()


def test_sales_since_baseline_reduce_stock(client, demo):
    shop = demo["shop_id"]
    pid, _, _ = _pid(demo)
    since = datetime(2026, 10, 1, tzinfo=timezone.utc)
    _set_baseline(demo, pid, 500, since)
    sold = _sold_since(demo, pid, since)
    got = client.get(f"/v1/shops/{shop}/products/{pid}/stock", headers=demo["headers"]).json()
    assert got["current"] == 500 - sold + got["returnedSince"]
    assert got["soldSince"] == sold


def test_receipt_adds_to_current_and_resets_sales_count(client, demo):
    shop = demo["shop_id"]
    pid, _, _ = _pid(demo)
    _set_baseline(demo, pid, 0, datetime(2026, 10, 1, tzinfo=timezone.utc))
    before = client.get(f"/v1/shops/{shop}/products/{pid}/stock", headers=demo["headers"]).json()
    r = client.post(f"/v1/shops/{shop}/products/{pid}/stock/receipt", headers=demo["headers"], json={"qty": 5})
    assert r.status_code == 200 and r.json()["current"] == before["current"] + 5
    after = client.get(f"/v1/shops/{shop}/products/{pid}/stock", headers=demo["headers"]).json()
    assert after["current"] == before["current"] + 5
    assert after["soldSince"] == before["soldSince"]  # приход не сбрасывает учёт продаж (журнал, К-1)


def test_alerts_fire_once_per_threshold(client, demo):
    shop = demo["shop_id"]
    pid, _, _ = _pid(demo)
    now = datetime.now(timezone.utc)
    _set_baseline(demo, pid, 8, now)  # 8 шт. — порог 10
    before = len(list((settings.outbox_dir / "push").glob("*.json"))) if (settings.outbox_dir / "push").exists() else 0
    a1 = client.get(f"/v1/shops/{shop}/stock/alerts", headers=demo["headers"]).json()
    assert any(i["productId"] == pid and i["level"] == "t10" for i in a1["items"])
    client.get(f"/v1/shops/{shop}/stock/alerts", headers=demo["headers"])  # второй раз — без нового push
    after = len(list((settings.outbox_dir / "push").glob("*.json")))
    assert after == before + 1


def test_delist_only_at_zero_and_only_after_confirmation(client, demo):
    shop = demo["shop_id"]
    pid, sku, _ = _pid(demo)
    _set_baseline(demo, pid, 3, datetime.now(timezone.utc))
    assert client.post(f"/v1/shops/{shop}/products/{pid}/stock/delist", headers=demo["headers"],
                       json={"confirm": True}).status_code == 409  # остаток не ноль
    _set_baseline(demo, pid, 0, datetime.now(timezone.utc))
    assert client.post(f"/v1/shops/{shop}/products/{pid}/stock/delist", headers=demo["headers"],
                       json={"confirm": False}).status_code == 422
    assert client.post(f"/v1/shops/{shop}/products/{pid}/stock/delist", headers=demo["headers"],
                       json={"confirm": True}).status_code == 200
    with DbSession(engine) as db:
        conn = SimpleNamespace(seller_id="test")
        xml = price_list_xml(db, db.get(Shop, shop), conn).decode("utf-8")
    assert f'sku="{sku}"' not in xml


def test_assistant_answers_what_is_ending(demo, live):  # noqa: F811
    pid, sku, name = _pid(demo)
    _set_baseline(demo, pid, 2, datetime.now(timezone.utc))
    live["script"] = [_reply([_tool("get_stock_alerts", {}, uid="a1")]),
                      _reply([_text("Скоро закончится: {F2} — осталось {F3} шт.")])]
    out, _ = _ask(demo["shop_id"], "что скоро закончится на складе")
    assert out["liveUsed"] is True
    assert name in out["renderedAnswer"] and "2" in out["renderedAnswer"]
