"""Подписка, пробный период, блокировка и хранение (ТЗ 2.1, разделы 8–9). Время подменяется параметром now."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app import billing
from app.config import settings
from app.db import engine
from app.models import Order, Product, Shop
from tests.conftest import login

T0 = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def enforced(monkeypatch):
    monkeypatch.setattr(settings, "billing_enforced", True)
    monkeypatch.setattr(settings, "billing_test_mode", True)
    return settings


@pytest.fixture
def outbox_count():
    def count() -> int:
        d = settings.outbox_dir
        return len(list(d.glob("*.eml"))) if d.exists() else 0
    return count


def _account(client, email, device=None):
    tokens = login(client, email)
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    if device:
        headers["X-Device-Id"] = device
    return headers


def _shop(client, headers, name="Магазин"):
    from tests.conftest import confirm_age
    confirm_age(client, headers)
    r = client.post("/v1/shops", headers=headers, json={"name": name, "timezone": "Asia/Almaty", "language": "ru"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_without_flag_nothing_is_blocked(client, demo):
    r = client.get(f"/v1/shops/{demo['shop_id']}/overview", headers=demo["headers"])
    assert r.status_code == 200


def test_new_shop_is_blocked_until_trial(client, enforced):
    headers = _account(client, "owner1@example.com")
    shop_id = _shop(client, headers)
    r = client.get(f"/v1/shops/{shop_id}/overview", headers=headers)
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "subscription_required"

    state = client.get(f"/v1/shops/{shop_id}/subscription", headers=headers).json()
    assert state["state"] == "none"
    assert state["trial_available"] is True
    assert state["price_text"] == "9 900 ₸ в месяц"


def test_trial_unblocks_the_shop(client, enforced):
    headers = _account(client, "owner2@example.com")
    shop_id = _shop(client, headers)
    trial = client.post(f"/v1/shops/{shop_id}/subscription/trial", headers=headers, json={})
    assert trial.status_code == 201, trial.text
    assert trial.json()["state"] == "trial"
    assert client.get(f"/v1/shops/{shop_id}/overview", headers=headers).status_code == 200


def test_device_header_does_not_change_trial_rules(client, enforced):
    """Телефон не учитывается (решение владельца 20.11.2026): заголовок устройства ни на что не влияет."""
    headers = _account(client, "owner3@example.com", device="phone-1")
    shop_id = _shop(client, headers)
    assert client.post(f"/v1/shops/{shop_id}/subscription/trial", headers=headers, json={}).status_code == 201
    # другой аккаунт с тем же заголовком устройства получает пробный период: защиты по телефону нет
    other = _account(client, "owner3b@example.com", device="phone-1")
    other_shop = _shop(client, other, name="Второй")
    assert client.post(f"/v1/shops/{other_shop}/subscription/trial", headers=other, json={}).status_code == 201


def test_same_email_cannot_get_second_trial(client, enforced):
    headers = _account(client, "owner3c@example.com")
    _shop(client, headers, name="Первый")
    second = _shop(client, headers, name="Второй")
    assert client.post(f"/v1/shops/{second}/subscription/trial", headers=headers, json={}).status_code == 201
    third = _shop(client, headers, name="Третий")
    r = client.post(f"/v1/shops/{third}/subscription/trial", headers=headers, json={})
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "trial_used"


def test_trial_is_not_given_twice_to_same_account(client, enforced):
    headers = _account(client, "owner4@example.com", device="phone-2")
    shop_id = _shop(client, headers)
    assert client.post(f"/v1/shops/{shop_id}/subscription/trial", headers=headers, json={}).status_code == 201
    shop_b = _shop(client, headers, name="Другой")
    r = client.post(f"/v1/shops/{shop_b}/subscription/trial", headers=headers, json={})
    assert r.status_code == 409


def test_trial_is_refused_outside_test_mode(client, monkeypatch):
    monkeypatch.setattr(settings, "billing_enforced", True)
    monkeypatch.setattr(settings, "billing_test_mode", False)
    headers = _account(client, "owner5@example.com")
    shop_id = _shop(client, headers)
    r = client.post(f"/v1/shops/{shop_id}/subscription/trial", headers=headers, json={})
    assert r.status_code == 501
    assert r.json()["error"]["code"] == "store_not_configured"


def test_store_verification_is_not_connected_yet(client, enforced):
    headers = _account(client, "owner6@example.com")
    shop_id = _shop(client, headers)
    r = client.post(f"/v1/shops/{shop_id}/subscription/verify", headers=headers, json={"receipt": "x"})
    assert r.status_code == 501


def test_access_ends_on_expiry_and_letters_follow_schedule(client, enforced, outbox_count):
    headers = _account(client, "owner7@example.com")
    shop_id = _shop(client, headers)
    with DbSession(engine) as db:
        shop = db.get(Shop, shop_id)
        # пробный период закончился сутки назад
        billing.start_trial(db, shop, "owner@example.com", None, now=T0 - timedelta(days=15))
        assert billing.has_access(billing.get_subscription(db, shop_id), T0) is False

    before = outbox_count()
    with DbSession(engine) as db:
        assert (shop_id, "letter_0") in billing.run_retention(db, now=T0)
    assert outbox_count() == before + 1
    assert client.get(f"/v1/shops/{shop_id}/overview", headers=headers).status_code == 403

    with DbSession(engine) as db:
        assert (shop_id, "letter_60") in billing.run_retention(db, now=T0 + timedelta(days=60))
        assert billing.run_retention(db, now=T0 + timedelta(days=61)) == []  # без повторов
        assert (shop_id, "letter_83") in billing.run_retention(db, now=T0 + timedelta(days=83))
    assert outbox_count() == before + 3


def test_data_is_deleted_on_day_90_and_account_stays(client, enforced):
    headers = _account(client, "owner8@example.com")
    shop_id = _shop(client, headers)
    with DbSession(engine) as db:
        shop = db.get(Shop, shop_id)
        billing.start_trial(db, shop, "owner@example.com", None, now=T0 - timedelta(days=15))
        db.add(Product(shop_id=shop_id, sku="K002", name="Товар", category="Без категории"))
        db.commit()
        done = billing.run_retention(db, now=T0 + timedelta(days=90))
        assert (shop_id, "deleted") in done
        assert db.scalars(select(Product).where(Product.shop_id == shop_id)).all() == []
        assert db.scalars(select(Order).where(Order.shop_id == shop_id)).all() == []
        assert db.get(Shop, shop_id) is not None
        assert billing.get_subscription(db, shop_id).deleted_at is not None


def test_renewal_before_day_90_cancels_the_countdown(client, enforced):
    headers = _account(client, "owner9@example.com")
    shop_id = _shop(client, headers)
    with DbSession(engine) as db:
        shop = db.get(Shop, shop_id)
        billing.start_trial(db, shop, "owner@example.com", None, now=T0 - timedelta(days=15))
        billing.run_retention(db, now=T0 + timedelta(days=60))
        billing.activate_paid(db, shop, until=T0 + timedelta(days=100), store="test", now=T0 + timedelta(days=61))
        assert billing.run_retention(db, now=T0 + timedelta(days=95)) == []
    assert client.get(f"/v1/shops/{shop_id}/overview", headers=headers).status_code == 200


def test_demo_is_never_blocked_or_retained(client, enforced, demo):
    assert client.get(f"/v1/shops/{demo['shop_id']}/overview", headers=demo["headers"]).status_code == 200
    with DbSession(engine) as db:
        assert all(s != demo["shop_id"] for s, _ in billing.run_retention(db, now=T0 + timedelta(days=200)))


def test_export_is_blocked_after_expiry_but_my_data_is_not(client, enforced):
    headers = _account(client, "owner10@example.com")
    shop_id = _shop(client, headers)
    with DbSession(engine) as db:
        shop = db.get(Shop, shop_id)
        billing.start_trial(db, shop, "owner@example.com", None, now=T0 - timedelta(days=15))
    assert client.get(f"/v1/shops/{shop_id}/exports/profit.xlsx", headers=headers).status_code == 403
    assert client.get("/v1/me/export", headers=headers).status_code == 200
