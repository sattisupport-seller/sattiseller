"""Подписка, пробный период, блокировка и хранение (ТЗ 2.1, разделы 8–9). Время подменяется параметром now."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app import billing
from app.config import settings
from app.db import engine
from app.device_trust import DeviceVerdict
from app.models import KaspiConnection, Order, Product, Shop
from tests.conftest import login

T0 = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def enforced(monkeypatch):
    monkeypatch.setattr(settings, "billing_enforced", True)
    monkeypatch.setattr(settings, "billing_test_mode", True)
    monkeypatch.setattr(settings, "device_check_mode", "fake")
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


def _kaspi(shop_id: str, seller: str) -> None:
    """Подключённый магазин Kaspi (без сети): пробный период — только после подключения (К-21)."""
    with DbSession(engine) as db:
        db.add(KaspiConnection(shop_id=shop_id, seller_id=seller, token_enc="x", price_key=uuid.uuid4().hex))
        db.commit()


def _phone(name: str) -> dict:
    return {"platform": "ios", "device_token": f"devicecheck-{name}"}


def _trial(client, headers, shop_id, phone="p1"):
    return client.post(f"/v1/shops/{shop_id}/subscription/trial", headers=headers, json=_phone(phone))


def _start_trial_directly(db, shop, now):
    """Пробный период в прошлом (для сроков хранения): Kaspi подключён, телефон проверен."""
    _kaspi(shop.id, f"seller-{shop.id[:8]}")
    billing.start_trial(db, shop, f"{shop.id}@example.com", DeviceVerdict(available=True, trial_used=False), now=now)


def test_new_shop_is_blocked_until_trial(client, enforced):
    headers = _account(client, "owner1@example.com")
    shop_id = _shop(client, headers)
    r = client.get(f"/v1/shops/{shop_id}/overview", headers=headers)
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "subscription_required"

    state = client.get(f"/v1/shops/{shop_id}/subscription", headers=headers).json()
    assert state["state"] == "none"
    assert state["trial_available"] is False  # до подключения Kaspi — только демо
    assert state["price_text"] == "9 900 ₸ в месяц"
    _kaspi(shop_id, "S-1")
    assert client.get(f"/v1/shops/{shop_id}/subscription", headers=headers).json()["trial_available"] is True


def test_trial_needs_kaspi_connection(client, enforced):
    headers = _account(client, "owner1b@example.com")
    shop_id = _shop(client, headers)
    r = _trial(client, headers, shop_id)
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "kaspi_required"


def test_trial_unblocks_the_shop(client, enforced):
    headers = _account(client, "owner2@example.com")
    shop_id = _shop(client, headers)
    _kaspi(shop_id, "S-2")
    trial = _trial(client, headers, shop_id)
    assert trial.status_code == 201, trial.text
    assert trial.json()["state"] == "trial"
    assert client.get(f"/v1/shops/{shop_id}/overview", headers=headers).status_code == 200


def test_second_account_on_same_phone_gets_no_trial(client, enforced):
    """Пробный период — один на телефон навсегда (решение владельца 23.11)."""
    headers = _account(client, "owner3@example.com")
    shop_id = _shop(client, headers)
    _kaspi(shop_id, "S-3")
    assert _trial(client, headers, shop_id, phone="same").status_code == 201
    other = _account(client, "owner3b@example.com")
    other_shop = _shop(client, other, name="Второй")
    _kaspi(other_shop, "S-3b")
    r = _trial(client, other, other_shop, phone="same")
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "trial_used_device"
    offer = client.post(f"/v1/shops/{other_shop}/subscription/offer", headers=other, json=_phone("same")).json()
    assert offer["trial_available"] is False
    assert offer["apple_product_id"] == settings.apple_product_plain  # продукт той же группы без вводного предложения
    assert offer["google_offer_id"] is None  # предложение с пробным периодом не показывать


def test_same_kaspi_shop_new_account_new_phone_gets_no_trial(client, enforced):
    """Один пробный период на магазин Kaspi навсегда (решение владельца 23.11, 01:39)."""
    first = _account(client, "owner3d@example.com")
    shop_a = _shop(client, first)
    _kaspi(shop_a, "SELLER-777")
    assert _trial(client, first, shop_a, phone="a").status_code == 201
    second = _account(client, "owner3e@example.com")
    shop_b = _shop(client, second)
    _kaspi(shop_b, "SELLER-777")
    r = _trial(client, second, shop_b, phone="b")
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "trial_used"


def test_unverified_phone_gets_no_trial(client, enforced):
    """Проверка телефона недоступна (эмулятор, Expo Go, нет ключей) — пробный период не даём."""
    headers = _account(client, "owner3f@example.com")
    shop_id = _shop(client, headers)
    _kaspi(shop_id, "S-3f")
    r = client.post(f"/v1/shops/{shop_id}/subscription/trial", headers=headers, json={})
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "trial_unavailable"


def test_same_email_cannot_get_second_trial(client, enforced):
    headers = _account(client, "owner3c@example.com")
    second = _shop(client, headers, name="Второй")
    _kaspi(second, "S-3c-2")
    assert _trial(client, headers, second, phone="c1").status_code == 201
    third = _shop(client, headers, name="Третий")
    _kaspi(third, "S-3c-3")
    r = _trial(client, headers, third, phone="c2")
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "trial_used"


def test_trial_is_refused_outside_test_mode(client, monkeypatch):
    monkeypatch.setattr(settings, "billing_enforced", True)
    monkeypatch.setattr(settings, "billing_test_mode", False)
    headers = _account(client, "owner5@example.com")
    shop_id = _shop(client, headers)
    r = client.post(f"/v1/shops/{shop_id}/subscription/trial", headers=headers, json={})
    assert r.status_code == 501
    assert r.json()["error"]["code"] == "store_not_configured"


def test_store_verification_without_keys_says_not_configured(client, enforced):
    headers = _account(client, "owner6@example.com")
    shop_id = _shop(client, headers)
    r = client.post(f"/v1/shops/{shop_id}/subscription/verify", headers=headers,
                    json={"store": "apple", "purchase_id": "2000000000000001"})
    assert r.status_code == 501
    assert r.json()["error"]["code"] == "store_not_configured"


def test_access_ends_on_expiry_and_letters_follow_schedule(client, enforced, outbox_count):
    headers = _account(client, "owner7@example.com")
    shop_id = _shop(client, headers)
    with DbSession(engine) as db:
        shop = db.get(Shop, shop_id)
        # пробный период закончился сутки назад
        _start_trial_directly(db, shop, now=T0 - timedelta(days=15))
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
        _start_trial_directly(db, shop, now=T0 - timedelta(days=15))
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
        _start_trial_directly(db, shop, now=T0 - timedelta(days=15))
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
        _start_trial_directly(db, shop, now=T0 - timedelta(days=15))
    assert client.get(f"/v1/shops/{shop_id}/exports/profit.xlsx", headers=headers).status_code == 403
    assert client.get("/v1/me/export", headers=headers).status_code == 200
