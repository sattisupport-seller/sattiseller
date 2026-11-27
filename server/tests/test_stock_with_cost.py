"""К-24 (решение владельца 27.11.2026, 09:53): остаток вводится вместе с себестоимостью; товар без остатка «не настроен»;
остаток — на момент ввода: продажи из истории его не уменьшают, продажи после ввода — уменьшают."""

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app import kaspi as kaspi_service
from app.config import settings
from app.db import engine
from app.models import KaspiCatalog, Order, OrderItem, Product, StockMovement
from tests.conftest import confirm_age, login

NOW = datetime.now(timezone.utc)


def _shop(client, monkeypatch, email):
    monkeypatch.setattr(settings, "billing_enforced", False)
    tokens = login(client, email)
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    confirm_age(client, headers)
    shop_id = client.post("/v1/shops", headers=headers, json={"name": "Магазин"}).json()["id"]
    with DbSession(engine) as db:
        p = Product(shop_id=shop_id, sku="CUP1", name="Кружка", category="Посуда")
        db.add(p)
        db.commit()
        return headers, shop_id, p.id


def _sale(shop_id, product_id, created, qty=1, status="completed"):
    with DbSession(engine) as db:
        o = Order(shop_id=shop_id, number=f"N{uuid.uuid4().hex[:8]}", created_at=created, status=status)
        db.add(o)
        db.flush()
        db.add(OrderItem(shop_id=shop_id, order_id=o.id, product_id=product_id, qty=qty, unit_price_minor=500_000))
        db.commit()


def _stock(client, headers, shop_id):
    return {i["productId"]: i for i in client.get(f"/v1/shops/{shop_id}/stock", headers=headers).json()["items"]}


def test_cost_with_stock_records_inventory_and_configures_product(client, monkeypatch):
    headers, shop_id, pid = _shop(client, monkeypatch, "st1@example.com")
    missing = client.get(f"/v1/shops/{shop_id}/products/missing-costs", headers=headers).json()["items"]
    assert missing[0]["needs_cost"] and missing[0]["needs_stock"]
    r = client.post(f"/v1/shops/{shop_id}/products/{pid}/cost-versions", headers=headers,
                    json={"purchase": "2800", "stock_qty": 12})
    assert r.status_code == 201, r.text
    with DbSession(engine) as db:
        inv = db.scalars(select(StockMovement).where(StockMovement.product_id == pid)).all()
    assert [(m.kind, m.qty) for m in inv] == [("inventory", 12)]
    assert client.get(f"/v1/shops/{shop_id}/products/missing-costs", headers=headers).json()["items"] == []
    assert _stock(client, headers, shop_id)[pid]["current"] == 12


def test_cost_without_stock_keeps_product_unconfigured(client, monkeypatch):
    headers, shop_id, pid = _shop(client, monkeypatch, "st2@example.com")
    client.post(f"/v1/shops/{shop_id}/products/{pid}/cost-versions", headers=headers, json={"purchase": "2800"})
    item = client.get(f"/v1/shops/{shop_id}/products/missing-costs", headers=headers).json()["items"][0]
    assert item["needs_cost"] is False and item["needs_stock"] is True
    overview = client.get(f"/v1/shops/{shop_id}/overview", headers=headers).json()
    assert overview["attention"]["not_configured_count"] == 1
    assert pid not in _stock(client, headers, shop_id)  # «Остаток не указан», уведомлений нет


def test_history_sale_does_not_reduce_stock_but_later_sale_does(client, monkeypatch):
    headers, shop_id, pid = _shop(client, monkeypatch, "st3@example.com")
    _sale(shop_id, pid, NOW - timedelta(days=30), qty=5)  # из загруженной истории
    client.post(f"/v1/shops/{shop_id}/cost-versions/bulk", headers=headers,
                json={"items": [{"product_id": pid, "purchase": "2800", "stock_qty": 10}]})
    assert _stock(client, headers, shop_id)[pid]["current"] == 10
    _sale(shop_id, pid, datetime.now(timezone.utc) + timedelta(seconds=1), qty=3)
    assert _stock(client, headers, shop_id)[pid]["current"] == 7


def test_bulk_stock_only_for_product_with_cost(client, monkeypatch):
    headers, shop_id, pid = _shop(client, monkeypatch, "st4@example.com")
    client.post(f"/v1/shops/{shop_id}/products/{pid}/cost-versions", headers=headers, json={"purchase": "2800"})
    r = client.post(f"/v1/shops/{shop_id}/cost-versions/bulk", headers=headers,
                    json={"items": [{"product_id": pid, "stock_qty": 0}]})  # 0 — можно
    assert r.status_code == 200, r.text
    assert client.get(f"/v1/shops/{shop_id}/products/missing-costs", headers=headers).json()["items"] == []
    bad = client.post(f"/v1/shops/{shop_id}/cost-versions/bulk", headers=headers, json={"items": [{"product_id": pid}]})
    assert bad.status_code == 422


def test_stock_hint_from_seller_price_list(client, monkeypatch):
    headers, shop_id, pid = _shop(client, monkeypatch, "st5@example.com")
    xml = ('<kaspi_catalog xmlns="kaspiShopping"><offers><offer sku="CUP1"><model>Кружка</model><availabilities>'
           '<availability available="yes" storeId="PP1" stockCount="4"/><availability available="yes" storeId="PP2" '
           'stockCount="3"/></availabilities><price>5000</price></offer></offers></kaspi_catalog>')
    with DbSession(engine) as db:
        db.add(KaspiCatalog(shop_id=shop_id, xml_text=xml, offers_count=1, imported_at=NOW))
        db.commit()
        assert kaspi_service.catalog_stock_hints(db, shop_id) == {"CUP1": 7}
    item = client.get(f"/v1/shops/{shop_id}/products/missing-costs", headers=headers).json()["items"][0]
    assert item["stock_hint"] == 7


def test_no_alerts_without_stock(client, monkeypatch):
    headers, shop_id, pid = _shop(client, monkeypatch, "st6@example.com")
    client.post(f"/v1/shops/{shop_id}/products/{pid}/cost-versions", headers=headers, json={"purchase": "2800"})
    _sale(shop_id, pid, datetime.now(timezone.utc), qty=100)
    body = client.get(f"/v1/shops/{shop_id}/stock/alerts", headers=headers).json()
    assert body["items"] == [] and body["endingSoon"] == []
