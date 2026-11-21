"""Этап 2 (2.1–2.5, 2.8): подключение Kaspi на моке — токен, синхронизация без дублей, сбои, прайс, отключение."""

import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session as DbSession

from app import api as api_module
from app import kaspi as kaspi_service
from app.config import settings
from app.db import engine
from app.kaspi_client import KaspiAuthError, KaspiClient, KaspiUnavailable
from app.models import KaspiConnection, Order, Product
from tests.kaspi_mock import VALID_TOKEN, MockKaspi


@pytest.fixture
def kaspi_on(monkeypatch):
    monkeypatch.setattr(settings, "kaspi_connection_enabled", True)


@pytest.fixture
def mock(monkeypatch):
    m = MockKaspi()

    def factory(token, **kwargs):
        return KaspiClient(token, transport=m.transport(), sleep=lambda s: None, min_interval=0)

    monkeypatch.setattr(api_module, "KaspiClient", factory)
    monkeypatch.setattr(kaspi_service, "client_for",
                        lambda conn: factory(kaspi_service.decrypt_token(conn.token_enc)))
    return m


def _connect(client, demo, token=VALID_TOKEN):
    return client.post(f"/v1/shops/{demo['shop_id']}/kaspi/connection",
                       json={"seller_id": "S-1", "token": token}, headers=demo["headers"])


def _count_kaspi_orders(shop_id):
    with DbSession(engine) as db:
        return db.query(Order).filter(Order.shop_id == shop_id, Order.number.like("KC%")).count()


def test_flag_is_off_by_default(client, demo):
    r = _connect(client, demo)
    assert r.status_code == 404


def test_token_is_stored_encrypted_and_never_returned(client, demo, kaspi_on, mock):
    r = _connect(client, demo)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "active" and VALID_TOKEN not in r.text
    with DbSession(engine) as db:
        conn = db.get(KaspiConnection, demo["shop_id"])
        assert VALID_TOKEN not in conn.token_enc
        assert kaspi_service.decrypt_token(conn.token_enc) == VALID_TOKEN


def test_wrong_token_is_refused_and_nothing_is_saved(client, demo, kaspi_on, mock):
    r = _connect(client, demo, token="wrong-token-0000000")
    assert r.status_code == 422 and r.json()["error"]["code"] == "kaspi_token_rejected"
    with DbSession(engine) as db:
        assert db.get(KaspiConnection, demo["shop_id"]) is None


def test_sync_imports_orders_and_repeat_sync_does_not_duplicate(client, demo, kaspi_on, mock):
    _connect(client, demo)
    mock.generate(50, now=datetime.now(timezone.utc))
    first = client.post(f"/v1/shops/{demo['shop_id']}/kaspi/sync", headers=demo["headers"])
    assert first.status_code == 200, first.text
    assert first.json()["added"] == 50
    assert _count_kaspi_orders(demo["shop_id"]) == 50
    second = client.post(f"/v1/shops/{demo['shop_id']}/kaspi/sync", headers=demo["headers"])
    assert second.json()["added"] == 0
    assert _count_kaspi_orders(demo["shop_id"]) == 50


def test_state_change_in_the_overlap_window_updates_the_same_order(client, demo, kaspi_on, mock):
    _connect(client, demo)
    now = datetime.now(timezone.utc)
    mock.generate(20, now=now)
    client.post(f"/v1/shops/{demo['shop_id']}/kaspi/sync", headers=demo["headers"])
    newest = mock.orders[-1]["id"]  # состояние NEW при генерации
    mock.set_state(newest, "COMPLETED")
    stats = client.post(f"/v1/shops/{demo['shop_id']}/kaspi/sync", headers=demo["headers"]).json()
    assert stats["updated"] == 1 and stats["added"] == 0
    with DbSession(engine) as db:
        order = db.query(Order).filter(Order.shop_id == demo["shop_id"], Order.number == newest).one()
        assert order.status == "completed" and order.completed_at is not None


def test_hundred_products_many_pages(client, demo, kaspi_on, mock):
    _connect(client, demo)
    mock.generate(250, now=datetime.now(timezone.utc), products=100)
    stats = client.post(f"/v1/shops/{demo['shop_id']}/kaspi/sync", headers=demo["headers"]).json()
    assert stats["added"] == 250 and stats["pages"] == 3
    with DbSession(engine) as db:
        assert db.query(Product).filter(Product.shop_id == demo["shop_id"], Product.sku.like("K%")).count() == 100


def test_failure_in_the_middle_keeps_progress_and_resumes_without_duplicates(client, demo, kaspi_on, mock):
    _connect(client, demo)
    mock.generate(250, now=datetime.now(timezone.utc))
    mock.fail_on_page = 1
    r = client.post(f"/v1/shops/{demo['shop_id']}/kaspi/sync", headers=demo["headers"])
    assert r.status_code == 503
    assert _count_kaspi_orders(demo["shop_id"]) == 100  # первая страница сохранилась
    with DbSession(engine) as db:
        conn = db.get(KaspiConnection, demo["shop_id"])
        assert conn.cursor_ms is not None and conn.last_error
    mock.fail_on_page = None
    r = client.post(f"/v1/shops/{demo['shop_id']}/kaspi/sync", headers=demo["headers"])
    assert r.status_code == 200, r.text
    assert _count_kaspi_orders(demo["shop_id"]) == 250


def test_429_is_retried_then_succeeds(client, demo, kaspi_on, mock):
    _connect(client, demo)
    mock.generate(5, now=datetime.now(timezone.utc))
    mock.fail_script = [429]
    r = client.post(f"/v1/shops/{demo['shop_id']}/kaspi/sync", headers=demo["headers"])
    assert r.status_code == 200 and r.json()["added"] == 5


def test_revoked_token_marks_the_connection(client, demo, kaspi_on, mock):
    _connect(client, demo)
    mock.token = "revoked-token-0000000"
    r = client.post(f"/v1/shops/{demo['shop_id']}/kaspi/sync", headers=demo["headers"])
    assert r.status_code == 422 and r.json()["error"]["code"] == "kaspi_token_rejected"
    status = client.get(f"/v1/shops/{demo['shop_id']}/kaspi/connection", headers=demo["headers"]).json()
    assert status["status"] == "token_invalid" and status["last_error"]


def test_price_list_lists_sold_products_and_stops_after_disconnect(client, demo, kaspi_on, mock):
    _connect(client, demo)
    mock.generate(30, now=datetime.now(timezone.utc), products=10)
    client.post(f"/v1/shops/{demo['shop_id']}/kaspi/sync", headers=demo["headers"])
    status = client.get(f"/v1/shops/{demo['shop_id']}/kaspi/connection", headers=demo["headers"]).json()
    path = status["price_url"]
    r = client.get(path)
    assert r.status_code == 200 and "xml" in r.headers["content-type"]
    root = ET.fromstring(r.content)
    offers = [o for o in root.findall("./offers/offer") if o.get("sku", "").startswith("K")]
    assert 1 <= len(offers) <= 10  # товары из заказов Kaspi; демо-товары тоже попадают в прайс
    assert all(int(o.find("price").text) > 0 for o in root.findall("./offers/offer"))
    assert client.get(path.rsplit("/", 1)[0] + "/wrong-key-000000000000000000000").status_code == 404
    assert client.delete(f"/v1/shops/{demo['shop_id']}/kaspi/connection", headers=demo["headers"]).status_code == 200
    assert client.get(path).status_code == 404
    assert client.get(f"/v1/shops/{demo['shop_id']}/kaspi/connection", headers=demo["headers"]).json()["status"] == "not_connected"


def test_deleting_the_shop_removes_the_kaspi_connection(client, demo, kaspi_on, mock):
    _connect(client, demo)
    with DbSession(engine) as db:
        db.execute(text("DELETE FROM shops WHERE id = :id"), {"id": demo["shop_id"]})
        db.commit()
    with DbSession(engine) as db:
        assert db.get(KaspiConnection, demo["shop_id"]) is None


def test_sync_rate_limit(client, demo, kaspi_on, mock):
    _connect(client, demo)
    codes = [client.post(f"/v1/shops/{demo['shop_id']}/kaspi/sync", headers=demo["headers"]).status_code for _ in range(13)]
    assert codes[:12] == [200] * 12 and codes[12] == 429


def test_client_gives_up_after_all_retries_on_server_errors():
    from tests.kaspi_mock import MockKaspi as M

    m = M(fail_script=[500, 500, 500, 500])
    c = KaspiClient(VALID_TOKEN, transport=m.transport(), sleep=lambda s: None, min_interval=0)
    with pytest.raises(KaspiUnavailable):
        c.list_orders(since_ms=0, page=0)


def test_client_treats_401_as_auth_error_without_retry():
    m = MockKaspi(token="other-token-0000000000")
    c = KaspiClient(VALID_TOKEN, transport=m.transport(), sleep=lambda s: None, min_interval=0)
    with pytest.raises(KaspiAuthError):
        c.list_orders(since_ms=0, page=0)
    assert m.requests_seen == 1


def test_periodic_sync_picks_only_due_active_connections(client, demo, kaspi_on, mock):
    """2.2: раз в 15 минут — только подключения без недавней синхронизации и с действующим токеном."""
    _connect(client, demo)
    mock.generate(3, now=datetime.now(timezone.utc))
    now = datetime.now(timezone.utc)
    with DbSession(engine) as db:
        done = kaspi_service.sync_due(db, now)
        assert done == [(demo["shop_id"], "synced")]
        assert kaspi_service.sync_due(db, now) == []  # только что синхронизировали
        later = now.replace(year=now.year) + timedelta(minutes=16)
        assert kaspi_service.sync_due(db, later) == [(demo["shop_id"], "synced")]
        conn = db.get(KaspiConnection, demo["shop_id"])
        conn.status = "token_invalid"
        db.commit()
        assert kaspi_service.sync_due(db, later + timedelta(hours=1)) == []
