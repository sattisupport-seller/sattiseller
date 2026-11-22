"""Склад (3.8 / PROPOSALS 18): остаток вносит продавец; помощник читает его инструментом get_stock; Kaspi не меняется."""

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.config import settings
from app.db import engine
from app.models import Product, ProductStock, Shop
from tests.test_ai_live import _ask, _reply, _text, _tool, live  # noqa: F401  (фикстура live)


def _sku_and_id(demo):
    with DbSession(engine) as db:
        p = db.scalars(select(Product).where(Product.shop_id == demo["shop_id"]).order_by(Product.sku)).first()
        return p.id, p.sku, p.name


def test_stock_put_then_get(client, demo):
    shop = demo["shop_id"]
    pid, _, _ = _sku_and_id(demo)
    assert client.get(f"/v1/shops/{shop}/products/{pid}/stock", headers=demo["headers"]).json()["qty"] is None
    put = client.put(f"/v1/shops/{shop}/products/{pid}/stock", headers=demo["headers"], json={"qty": 12})
    assert put.status_code == 200 and put.json()["qty"] == 12
    assert client.get(f"/v1/shops/{shop}/products/{pid}/stock", headers=demo["headers"]).json()["qty"] == 12
    assert client.put(f"/v1/shops/{shop}/products/{pid}/stock", headers=demo["headers"], json={"qty": -1}).status_code == 422


def test_stock_of_other_shop_product_is_not_found(client, demo):
    shop = demo["shop_id"]
    pid, _, _ = _sku_and_id(demo)
    with DbSession(engine) as db:
        other = Shop(name="Другой", timezone="Asia/Almaty")
        db.add(other)
        db.commit()
        other_id = other.id
    r = client.get(f"/v1/shops/{other_id}/products/{pid}/stock", headers=demo["headers"])
    assert r.status_code in (403, 404)


def test_assistant_reads_stock_when_entered(demo, live):
    pid, sku, name = _sku_and_id(demo)
    with DbSession(engine) as db:
        db.add(ProductStock(shop_id=demo["shop_id"], product_id=pid, qty=7))
        db.commit()
    live["script"] = [_reply([_tool("get_stock", {"sku": sku}, uid="s1")]),
                      _reply([_text("На складе {F2} шт. у товара {F1}.")])]
    out, _ = _ask(demo["shop_id"], "сколько осталось товара на складе")
    assert out["liveUsed"] is True
    assert "7" in out["renderedAnswer"] and name in out["renderedAnswer"]


def test_assistant_says_stock_not_entered(demo, live):
    _, sku, _ = _sku_and_id(demo)
    live["script"] = [_reply([_tool("get_stock", {"sku": sku}, uid="s2")]),
                      _reply([_text("Остаток по товару не внесён: внесите его в карточке товара.")])]
    out, _ = _ask(demo["shop_id"], "сколько осталось товара на складе")
    assert out["liveUsed"] is True
    assert "не внесён" in out["renderedAnswer"]
