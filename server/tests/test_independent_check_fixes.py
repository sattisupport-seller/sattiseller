"""К-30 п.3: исправления по независимой перепроверке функций (D1–D9)."""

from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app import kaspi as kaspi_service
from app.config import settings
from app.db import engine
from app.kaspi_client import KaspiClient
from app.models import AIUsageEvent, KaspiConnection, Order, OrderItem, ReturnEvent
from tests.kaspi_mock import DAY_MS
from tests.test_seller_access import _connect, _seller, env  # noqa: F401

NOW = datetime.now(timezone.utc)


def _client(mock):
    return KaspiClient(mock.token, transport=mock.transport(), sleep=lambda s: None, min_interval=0)


def _order(mock, code, created, state, rows, credit=False, to_warehouse=None):
    ms = int(created.timestamp() * 1000)
    mock.entries[code] = rows
    attrs = {"state": state, "creationDate": ms, "completedDate": ms + DAY_MS,
             "paymentMode": "PAY_WITH_CREDIT" if credit else "PREPAID"}
    if to_warehouse is not None:
        attrs["returnedToWarehouse"] = to_warehouse
    mock.orders.append({"id": code, "type": "orders", "attributes": attrs,
                        "relationships": {"entries": {"links": {"related": f"/orders/{code}/entries"}}}})


def _shop(client, env, monkeypatch, email, seller):  # noqa: F811
    monkeypatch.setattr(settings, "billing_enforced", False)
    headers, shop_id = _seller(client, email)
    assert _connect(client, headers, shop_id, seller=seller).status_code == 201
    return headers, shop_id


def test_d1_nightly_loop_decides_without_import_error():
    from app.scheduler import NIGHTLY_HOUR, nightly_due

    almaty_0259 = datetime(2026, 11, 27, 21, 59, tzinfo=timezone.utc)  # 02:59 по Алматы
    almaty_0300 = datetime(2026, 11, 27, 22, 0, tzinfo=timezone.utc)   # 03:00 по Алматы, 28.11
    assert NIGHTLY_HOUR == 3
    assert nightly_due(almaty_0259, None) is False
    assert nightly_due(almaty_0300, None) is True
    assert nightly_due(almaty_0300, date(2026, 11, 28)) is False  # уже было сегодня


def test_d2_recent_orders_are_refreshed_even_with_many_old_ones(client, env, monkeypatch):  # noqa: F811
    headers, shop_id = _shop(client, env, monkeypatch, "d2@example.com", "D2-1")
    for i in range(3):  # старые, выданы давно — окно возврата закрыто
        _order(env, f"OLD{i}", NOW - timedelta(days=80), "COMPLETED", [{"id": f"EO{i}", "idx": 0, "qty": 1, "basePrice": 1000}])
    _order(env, "NEW1", NOW - timedelta(days=2), "COMPLETED", [{"id": "EN1", "idx": 0, "qty": 1, "basePrice": 1000}])
    client.post(f"/v1/shops/{shop_id}/kaspi/sync", headers=headers)
    env.set_state("NEW1", "RETURNED")
    monkeypatch.setattr(kaspi_service, "MAX_OPEN_REFRESH", 1)  # места только на один заказ
    with DbSession(engine) as db:
        res = kaspi_service.refresh_open_orders(db, db.get(KaspiConnection, shop_id), _client(env), NOW)
        order = db.scalar(select(Order).where(Order.number == "NEW1"))
        assert res["checked"] == 1 and order.status == "returned"  # свежий проверен, а не самый старый


def test_d3_special_access_restarts_retention(client, monkeypatch):
    from app import billing
    from app.billing import RetentionEvent, Subscription, run_retention
    from app.seller_access import SellerNumber, SpecialAccess
    from tests.conftest import confirm_age, login

    tokens = login(client, "d3@example.com")
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    confirm_age(client, headers)
    shop_id = client.post("/v1/shops", headers=headers, json={"name": "М"}).json()["id"]
    lapsed = NOW - timedelta(days=200)
    with DbSession(engine) as db:
        db.add(Subscription(shop_id=shop_id, state="active", access_until=lapsed, lapsed_at=lapsed, store="apple"))
        db.add(SellerNumber(number="31313131", seller_hash="d3-hash", user_id=tokens["user"]["id"], shop_id=shop_id))
        db.add(SpecialAccess(number="31313131", starts_at=lapsed + timedelta(days=5),
                             ends_at=NOW - timedelta(days=1), comment=""))  # доступ от владельца закончился вчера
        db.commit()
        billing.reset_retention(db, shop_id)  # как при выдаче доступа в админке
        db.commit()
        done = [d for d in run_retention(db, NOW) if d[0] == shop_id]
        sub = db.get(Subscription, shop_id)
        assert ("deleted", ) not in [(k,) for _, k in done]  # данные не удалены
        assert [k for _, k in done] == ["letter_0"]  # отсчёт начался заново — только первое письмо
        assert abs((billing._aware(sub.lapsed_at) - (NOW - timedelta(days=1))).total_seconds()) < 5
        assert db.scalars(select(RetentionEvent).where(RetentionEvent.shop_id == shop_id)).all()


def test_d4_historic_return_is_dated_by_delivery_not_sync(client, env, monkeypatch):  # noqa: F811
    headers, shop_id = _shop(client, env, monkeypatch, "d4@example.com", "D4-1")
    created = NOW - timedelta(days=40)
    _order(env, "R40", created, "RETURNED", [{"id": "ER40", "idx": 0, "qty": 1, "basePrice": 5000}], to_warehouse=True)
    for _ in range(5):
        client.post(f"/v1/shops/{shop_id}/kaspi/sync", headers=headers)
    with DbSession(engine) as db:
        order = db.scalar(select(Order).where(Order.number == "R40"))
        ev = db.scalar(select(ReturnEvent).join(OrderItem, OrderItem.id == ReturnEvent.item_id)
                       .where(OrderItem.order_id == order.id))
        assert ev is not None
        def aware(dt):
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)

        assert abs((aware(ev.confirmed_at) - aware(order.completed_at)).total_seconds()) < 5
        assert (NOW - aware(ev.confirmed_at)).days >= 30  # не день подключения


def test_d5_future_installment_rate_does_not_apply_to_todays_order(client, env, monkeypatch):  # noqa: F811
    headers, shop_id = _shop(client, env, monkeypatch, "d5@example.com", "D5-1")
    future = (NOW + timedelta(days=20)).date().isoformat()
    assert client.post(f"/v1/shops/{shop_id}/commissions", headers=headers,
                       json={"category": "Рассрочка Kaspi", "rate_percent": "12", "effective_from": future}).status_code == 201
    _order(env, "CR1", NOW - timedelta(days=1), "COMPLETED", [{"id": "ECR1", "idx": 0, "qty": 1, "basePrice": 8000}], credit=True)
    client.post(f"/v1/shops/{shop_id}/kaspi/sync", headers=headers)
    with DbSession(engine) as db:
        order = db.scalar(select(Order).where(Order.number == "CR1"))
        item = db.scalar(select(OrderItem).where(OrderItem.order_id == order.id))
        assert item.commission_rate_bp == 1300  # 13,0 % по умолчанию (К-33 А2): тариф с будущей даты ещё не действует


def test_d7_period_with_only_a_return_shows_negative_profit(client, env, monkeypatch):  # noqa: F811
    from app.models import Shop
    from app.periods import Period
    from app.reports import base_for, product_stats

    headers, shop_id = _shop(client, env, monkeypatch, "d7@example.com", "D7-1")
    _order(env, "S1", NOW - timedelta(days=60), "COMPLETED", [{"id": "ES1", "idx": 0, "qty": 1, "basePrice": 5000}])
    for _ in range(5):
        client.post(f"/v1/shops/{shop_id}/kaspi/sync", headers=headers)
    pid = client.get(f"/v1/shops/{shop_id}/products/missing-costs", headers=headers).json()["items"][0]["product_id"]
    client.post(f"/v1/shops/{shop_id}/cost-versions/bulk", headers=headers,
                json={"items": [{"product_id": pid, "purchase": "2000", "stock_qty": 1}], "apply_to_history": True})
    client.post(f"/v1/shops/{shop_id}/commissions", headers=headers, json={"category": "Посуда для кухни", "rate_percent": "10"})
    with DbSession(engine) as db:  # возврат сегодня (продажа — 60 дней назад)
        item = db.scalar(select(OrderItem).join(Order).where(Order.number == "S1"))
        db.add(ReturnEvent(item_id=item.id, shop_id=shop_id, returned_qty=1, confirmed_at=NOW, refund_minor=500000,
                           commission_returned_minor=50000, delivery_returned_minor=0, reverse_delivery_minor=0,
                           goods_sellable=True))
        db.commit()
        shop = db.get(Shop, shop_id)
        data, facts = base_for(db, shop)
        today = NOW.astimezone(__import__("zoneinfo").ZoneInfo("Asia/Almaty")).date()
        stats = product_stats(data, facts, Period(today - timedelta(days=6), today))
    st = stats[pid]
    assert st.profit is not None and st.profit < 0  # раньше — None («нет данных»)


def test_d8_empty_entries_do_not_delete_items(client, env, monkeypatch):  # noqa: F811
    headers, shop_id = _shop(client, env, monkeypatch, "d8@example.com", "D8-1")
    _order(env, "E1", NOW - timedelta(days=2), "COMPLETED", [{"id": "EE1", "idx": 0, "qty": 2, "basePrice": 1000}])
    client.post(f"/v1/shops/{shop_id}/kaspi/sync", headers=headers)
    env.entries["E1"] = []  # сбой Kaspi: пустой список позиций
    with DbSession(engine) as db:
        kaspi_service.refresh_open_orders(db, db.get(KaspiConnection, shop_id), _client(env), NOW)
        order = db.scalar(select(Order).where(Order.number == "E1"))
        assert db.scalars(select(OrderItem).where(OrderItem.order_id == order.id)).all()


def test_d9_ai_day_starts_at_almaty_midnight(client):
    from app.ai import check_quota
    from tests.conftest import confirm_age, login

    tokens = login(client, "d9@example.com")
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    confirm_age(client, headers)
    shop_id = client.post("/v1/shops", headers=headers, json={"name": "М"}).json()["id"]
    user_id = tokens["user"]["id"]
    now = datetime(2026, 11, 28, 4, 0, tzinfo=timezone.utc)          # 09:00 по Алматы 28.11
    before_midnight = datetime(2026, 11, 27, 18, 30, tzinfo=timezone.utc)  # 23:30 по Алматы 27.11 — вчера
    after_midnight = datetime(2026, 11, 27, 19, 30, tzinfo=timezone.utc)   # 00:30 по Алматы 28.11 — сегодня
    with DbSession(engine) as db:
        for t in (before_midnight, after_midnight):
            db.add(AIUsageEvent(user_id=user_id, shop_id=shop_id, created_at=t, tool_calls=0, kind="ask", cost_micro_usd=0))
        db.commit()
        left = check_quota(db, user_id, shop_id, now)
    assert left == settings.ai_daily_limit - 1 - 1  # учтён только запрос после полуночи по Алматы
