"""К-33 А3: режим презентации — пример остатков и себестоимости на данных продавца; в Kaspi ничего не уходит."""

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.config import settings
from app.db import engine
from app.models import AuditEvent, KaspiConnection, ProductCostVersion, StockMovement
from tests.test_seller_access import _admin, _connect, _number, _seller, env  # noqa: F401 — фикстура Kaspi на моке


def _setup(client, env, monkeypatch, email="pres@example.com"):  # noqa: F811
    monkeypatch.setattr(settings, "billing_enforced", False)
    headers, shop_id = _seller(client, email)
    assert _connect(client, headers, shop_id).status_code == 201
    env.generate(120, now=datetime.now(timezone.utc), days=40, products=8)
    assert client.post(f"/v1/shops/{shop_id}/kaspi/sync", headers=headers).status_code == 200
    return headers, shop_id, _number(client, headers), _admin(client)


def _presentation(client, admin, number, enabled):
    return client.post(f"/v1/admin/sellers/{number}/presentation", headers=admin,
                       json={"enabled": enabled, "confirm": True})


def _coverage(client, headers, shop_id):
    return client.get(f"/v1/shops/{shop_id}/overview?period=30d", headers=headers).json()["kpi"]["coverage_bp"]


def test_examples_fill_stock_and_cost_and_are_marked(client, env, monkeypatch):  # noqa: F811
    headers, shop_id, number, admin = _setup(client, env, monkeypatch)
    assert _coverage(client, headers, shop_id) == 0  # себестоимости нет — прибыль не считается
    r = _presentation(client, admin, number, True)
    assert r.status_code == 200, r.text
    pres = r.json()["presentation"]
    assert pres["stock_examples"] == 8 and pres["cost_examples"] >= 1 and pres["low_stock_products"] == 3
    assert r.json()["presentation_mode"] is True

    shop = client.get("/v1/shops", headers=headers).json()["items"][0]
    assert shop["presentation_mode"] is True and shop["example_cost_pct"] == 60
    stock = client.get(f"/v1/shops/{shop_id}/stock", headers=headers).json()["items"]
    assert stock and all(i["example"] for i in stock)
    assert sum(1 for i in stock if i["current"] <= 1) >= 3  # несколько товаров с 0–1 шт. — показать автоснятие
    assert _coverage(client, headers, shop_id) > 0  # все инструменты работают на его данных

    preview = client.get(f"/v1/shops/{shop_id}/stock/delist-preview", headers=headers).json()
    assert preview["count"] >= 1 and all(i["current"] <= 0 or i["reason"] == "delisted" for i in preview["items"])
    assert "ничего не меняется" in preview["note"]


def test_cost_percent_changes_only_examples(client, env, monkeypatch):  # noqa: F811
    headers, shop_id, number, admin = _setup(client, env, monkeypatch)
    _presentation(client, admin, number, True)
    with DbSession(engine) as db:
        before = {v.product_id: v.purchase_minor for v in db.scalars(select(ProductCostVersion)).all()}
    r = client.post(f"/v1/shops/{shop_id}/presentation/cost-percent", headers=headers, json={"percent": 30})
    assert r.status_code == 200 and r.json()["cost_pct"] == 30
    with DbSession(engine) as db:
        after = {v.product_id: v.purchase_minor for v in db.scalars(select(ProductCostVersion)).all()}
    assert all(after[p] < before[p] for p in before)  # 30 % < 60 %
    assert all(after[p] % 100 == 0 for p in after)  # целые тенге
    assert client.post(f"/v1/shops/{shop_id}/presentation/cost-percent", headers=headers,
                       json={"percent": 0}).status_code == 422


def test_own_numbers_replace_examples_for_whole_history(client, env, monkeypatch):  # noqa: F811
    headers, shop_id, number, admin = _setup(client, env, monkeypatch)
    _presentation(client, admin, number, True)
    pid = client.get(f"/v1/shops/{shop_id}/stock", headers=headers).json()["items"][0]["productId"]
    r = client.post(f"/v1/shops/{shop_id}/products/{pid}/cost-versions", headers=headers,
                    json={"purchase": "1234", "stock_qty": 7})
    assert r.status_code == 201, r.text
    assert r.json()["effective_from"] is None  # своя цифра — на всю историю, как первый ввод
    with DbSession(engine) as db:
        sources = {v.source for v in db.scalars(select(ProductCostVersion).where(ProductCostVersion.product_id == pid))}
        assert sources == {"manual"}
        assert not db.scalars(select(StockMovement).where(StockMovement.product_id == pid,
                                                          StockMovement.example.is_(True))).all()
    row = next(i for i in client.get(f"/v1/shops/{shop_id}/stock", headers=headers).json()["items"]
               if i["productId"] == pid)
    assert row["example"] is False and row["current"] == 7
    # повторное включение режима не трогает цифры продавца
    _presentation(client, admin, number, True)
    with DbSession(engine) as db:
        assert {v.source for v in db.scalars(select(ProductCostVersion)
                                             .where(ProductCostVersion.product_id == pid))} == {"manual"}


def test_price_list_is_not_served_in_presentation_mode(client, env, monkeypatch):  # noqa: F811
    headers, shop_id, number, admin = _setup(client, env, monkeypatch)
    _presentation(client, admin, number, True)
    with DbSession(engine) as db:
        key = db.get(KaspiConnection, shop_id).price_key
    r = client.get(f"/v1/kaspi/price/{shop_id}/{key}")
    assert r.status_code == 503 and r.headers["Retry-After"] == "3600"  # Kaspi оставит прежний прайс продавца
    assert all(method == "GET" for method, _path in env.methods_seen)  # в Kaspi — только чтение


def test_turning_off_removes_examples_and_is_audited(client, env, monkeypatch):  # noqa: F811
    headers, shop_id, number, admin = _setup(client, env, monkeypatch)
    _presentation(client, admin, number, True)
    r = _presentation(client, admin, number, False)
    assert r.status_code == 200 and r.json()["presentation_mode"] is False
    with DbSession(engine) as db:
        assert not db.scalars(select(ProductCostVersion).where(ProductCostVersion.source == "example")).all()
        assert not db.scalars(select(StockMovement).where(StockMovement.example.is_(True))).all()
        actions = {e.action for e in db.scalars(select(AuditEvent)).all()}
    assert {"presentation_on", "presentation_off"} <= actions
    assert client.post(f"/v1/shops/{shop_id}/presentation/cost-percent", headers=headers,
                       json={"percent": 50}).status_code == 409


def test_presentation_needs_confirmation_and_admin(client, env, monkeypatch):  # noqa: F811
    headers, shop_id, number, admin = _setup(client, env, monkeypatch)
    assert client.post(f"/v1/admin/sellers/{number}/presentation", headers=admin,
                       json={"enabled": True}).status_code == 422
    assert client.post(f"/v1/admin/sellers/{number}/presentation", headers=headers,
                       json={"enabled": True, "confirm": True}).status_code in (401, 403, 404)  # не владелец: админки «нет»
