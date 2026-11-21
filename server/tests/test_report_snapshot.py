"""1.17: исходные данные отчётов кэшируются между запросами и сбрасываются при записи в магазин."""

from app import reportcache, reports
from app.db import SessionLocal
from app.models import Order, Shop


def test_snapshot_is_reused_until_invalidated(monkeypatch):
    calls = []
    reportcache.clear()
    value = object()
    assert reportcache.snapshot("shop-a", lambda: (calls.append(1), value)[1]) is value
    assert reportcache.snapshot("shop-a", lambda: (calls.append(1), value)[1]) is value
    assert len(calls) == 1
    reportcache.invalidate("shop-a")
    reportcache.snapshot("shop-a", lambda: (calls.append(1), value)[1])
    assert len(calls) == 2


def test_snapshot_store_is_bounded(monkeypatch):
    monkeypatch.setattr(reportcache, "MAX_SNAPSHOTS", 3)
    reportcache.clear()
    for n in range(6):
        reportcache.snapshot(f"s{n}", lambda: n)
    assert len(reportcache._snapshots) == 3


def test_base_holds_plain_copies_not_session_objects(demo):
    with SessionLocal() as db:
        shop = db.get(Shop, demo["shop_id"])
        data, facts = reports.base_for(db, shop)
    assert data.orders and not isinstance(data.orders[0], Order)
    assert hasattr(data.orders[0], "items") and hasattr(data.orders[0].items[0], "returns")
    assert facts


def test_cost_change_shows_up_in_reports_after_the_write(client, demo):
    products = client.get(f"/v1/shops/{demo['shop_id']}/products?period=30d", headers=demo["headers"]).json()
    before = client.get(f"/v1/shops/{demo['shop_id']}/products?period=30d", headers=demo["headers"]).json()
    assert before == products
    pid = products["items"][0]["product_id"]
    body = {"purchase": "1", "delivery_to_warehouse": "0", "packaging": "0", "other": "0",
            "effective_from": "2026-01-01", "apply_to_history": True}
    r = client.post(f"/v1/shops/{demo['shop_id']}/products/{pid}/cost-versions", json=body, headers=demo["headers"])
    assert r.status_code == 201, r.text
    after = client.get(f"/v1/shops/{demo['shop_id']}/products?period=30d", headers=demo["headers"]).json()
    assert after != before
