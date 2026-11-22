"""1.16: демо из шаблона одним INSERT ... SELECT даёт те же данные, что генерация заново (на любой дате)."""

import uuid
from datetime import timedelta

from sqlalchemy.orm import Session as DbSession

from app.db import engine
from app.demo import generate_demo
from app.demo_template import TEMPLATE_ANCHOR, TEMPLATE_SHOP_ID, copy_template, create_demo_from_template, ensure_template
from app.billing import wipe_shop_content
from app.models import (
    CommissionPreset,
    ExpenseEntry,
    Order,
    OrderItem,
    Product,
    ProductCostVersion,
    ReturnEvent,
    Shop,
)

SHIFT_DAYS = 37  # копия на дату, отличную от даты шаблона — сдвиг дат обязан совпасть с генерацией


def _snapshot(db: DbSession, shop_id: str) -> dict:
    """Бизнес-данные магазина без служебных id: сравнивается между способами создания."""
    sku_by_product = {p.id: p.sku for p in db.query(Product).filter(Product.shop_id == shop_id)}
    order_number = {o.id: o.number for o in db.query(Order).filter(Order.shop_id == shop_id)}
    item_key = {}
    items = []
    for i in db.query(OrderItem).filter(OrderItem.shop_id == shop_id):
        key = (order_number[i.order_id], sku_by_product[i.product_id])
        item_key[i.id] = key
        items.append((*key, i.qty, i.unit_price_minor, i.buyer_delivery_minor, i.commission_rate_bp))
    return {
        "products": sorted((p.sku, p.name, p.category) for p in db.query(Product).filter(Product.shop_id == shop_id)),
        "presets": sorted((c.category, c.rate_bp, c.effective_from, c.source, c.verified, c.demo)
                          for c in db.query(CommissionPreset).filter(CommissionPreset.shop_id == shop_id)),
        "costs": sorted((sku_by_product[v.product_id], v.purchase_minor, v.delivery_to_warehouse_minor,
                         v.packaging_minor, v.other_minor, v.effective_from, v.source, v.cancelled)
                        for v in db.query(ProductCostVersion).filter(ProductCostVersion.shop_id == shop_id)),
        "orders": sorted((o.number, o.status, o.created_at, o.completed_at)
                         for o in db.query(Order).filter(Order.shop_id == shop_id)),
        "items": sorted(items, key=repr),
        "returns": sorted((*item_key[r.item_id], r.returned_qty, r.confirmed_at, r.refund_minor,
                           r.commission_returned_minor, r.delivery_returned_minor, r.reverse_delivery_minor,
                           r.goods_sellable)
                          for r in db.query(ReturnEvent).filter(ReturnEvent.shop_id == shop_id)),
        "expenses": sorted((e.kind, e.amount_minor, e.period_start, e.period_end, e.source)
                           for e in db.query(ExpenseEntry).filter(ExpenseEntry.shop_id == shop_id)),
    }


def test_copy_matches_generation_on_another_date():
    day = TEMPLATE_ANCHOR + timedelta(days=SHIFT_DAYS)
    with DbSession(engine) as db:
        generated = generate_demo(db, day)
        copied = create_demo_from_template(db, day)
        db.commit()
        expected = _snapshot(db, generated.id)
        actual = _snapshot(db, copied.id)
    assert len(expected["orders"]) == 300
    assert len(expected["returns"]) > 0
    assert actual == expected


def test_copy_ids_are_new_and_unique_per_shop():
    with DbSession(engine) as db:
        first = create_demo_from_template(db, TEMPLATE_ANCHOR)
        second = create_demo_from_template(db, TEMPLATE_ANCHOR)
        db.commit()
        ids_first = {p.id for p in db.query(Product).filter(Product.shop_id == first.id)}
        ids_second = {p.id for p in db.query(Product).filter(Product.shop_id == second.id)}
        assert len(ids_first) == 40 and not ids_first & ids_second
        assert db.query(Shop).filter(Shop.id == TEMPLATE_SHOP_ID).count() == 1


def test_reset_restores_the_copy_for_the_same_date():
    day = TEMPLATE_ANCHOR + timedelta(days=SHIFT_DAYS)
    with DbSession(engine) as db:
        shop = create_demo_from_template(db, day)
        db.commit()
        before = _snapshot(db, shop.id)
        wipe_shop_content(db, shop.id)
        copy_template(db, shop.id, day)
        db.commit()
        assert _snapshot(db, shop.id) == before


def test_ensure_template_is_idempotent():
    with DbSession(engine) as db:
        ensure_template(db)
        ensure_template(db)
        assert db.query(Order).filter(Order.shop_id == TEMPLATE_SHOP_ID).count() == 300


def test_demo_session_uses_template_and_stays_separate(client):
    first = client.post("/v1/demo/session", headers={"X-Device-Id": f"tpl-{uuid.uuid4().hex[:8]}"})
    second = client.post("/v1/demo/session", headers={"X-Device-Id": f"tpl-{uuid.uuid4().hex[:8]}"})
    assert first.status_code == 200 and second.status_code == 200
    assert first.json()["shop_id"] != second.json()["shop_id"]
    headers = {"Authorization": f"Bearer {first.json()['access_token']}"}
    overview = client.get(f"/v1/shops/{first.json()['shop_id']}/overview?period=30d", headers=headers)
    assert overview.status_code == 200


def test_copied_cost_versions_are_created_now_not_on_template_date():
    """Регрессия: created_at версий затрат из шаблона в будущем ломал защиту от повторной отправки (QA-06)."""
    from datetime import datetime, timezone

    with DbSession(engine) as db:
        shop = create_demo_from_template(db, TEMPLATE_ANCHOR + timedelta(days=SHIFT_DAYS))
        db.commit()
        created = [v.created_at for v in db.query(ProductCostVersion).filter(ProductCostVersion.shop_id == shop.id)]
    assert created
    now = datetime.now(timezone.utc)
    for ts in created:
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        assert abs((now - ts).total_seconds()) < 3600
