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


def _set_admin_flag(value: bool) -> None:
    from datetime import datetime as _dt

    from app.admin import FeatureFlag

    with DbSession(engine) as db:
        row = db.get(FeatureFlag, "kaspi_connection") or FeatureFlag(key="kaspi_connection")
        row.enabled = value
        row.updated_at = _dt.now(timezone.utc)
        db.add(row)
        db.commit()


@pytest.fixture
def kaspi_on(monkeypatch):
    """Включены и переменная KASPI_ENABLED на сервере, и флаг в админке."""
    monkeypatch.setattr(settings, "kaspi_connection_enabled", True)
    _set_admin_flag(True)


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


def test_admin_flag_alone_is_not_enough(client, demo, monkeypatch, mock):
    monkeypatch.setattr(settings, "kaspi_connection_enabled", False)
    _set_admin_flag(True)
    assert _connect(client, demo).status_code == 404


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
    assert root.tag == "{kaspiShopping}kaspi_catalog"  # пространство имён из документации Kaspi
    offers = [o for o in root.findall("./{kaspiShopping}offers/{kaspiShopping}offer") if o.get("sku", "").startswith("K")]
    assert 1 <= len(offers) <= 10  # товары из заказов Kaspi; демо-товары тоже попадают в прайс
    assert all(int(o.find("{kaspiShopping}price").text) > 0 for o in root.findall("./{kaspiShopping}offers/{kaspiShopping}offer"))
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


def test_kaspi_orders_feed_the_profit_figures_exactly(client, demo, kaspi_on, mock):
    """К-2 п.1: заказы Kaspi на моке → цифры обзора. Прирост выручки = сумма позиций выполненных заказов Kaspi
    за период; отменённые не входят. Сравниваем дельту: демо-заказы магазина лежат за пределами 30 дней."""
    def _net_sales():
        ov = client.get(f"/v1/shops/{demo['shop_id']}/overview?period=30d", headers=demo["headers"])
        assert ov.status_code == 200, ov.text
        return ov.json()["kpi"]

    before = _net_sales()["net_sales_minor"]
    _connect(client, demo)
    mock.generate(6, now=datetime.now(timezone.utc), days=5, state_cycle=["COMPLETED", "CANCELLED"], products=2)
    r = client.post(f"/v1/shops/{demo['shop_id']}/kaspi/sync", headers=demo["headers"])
    assert r.status_code == 200, r.text
    from app.models import OrderItem

    with DbSession(engine) as db:
        kaspi_completed = db.query(Order).filter(Order.shop_id == demo["shop_id"], Order.number.like("KC%"),
                                                 Order.status == "completed").all()
        kaspi_cancelled = db.query(Order).filter(Order.shop_id == demo["shop_id"], Order.number.like("KC%"),
                                                 Order.status == "cancelled").all()
        assert kaspi_completed and kaspi_cancelled, "в моке должны быть и выполненные, и отменённые заказы Kaspi"
        expected = 0
        for o in kaspi_completed:
            for it in db.query(OrderItem).filter(OrderItem.order_id == o.id):
                expected += int(it.unit_price_minor) * int(it.qty)
    after = _net_sales()
    assert after["net_sales_minor"] - before == expected, (after["net_sales_minor"] - before, expected)
    assert isinstance(after["profit_minor"], int) and 0 <= after["coverage_bp"] <= 10000


def test_orders_request_uses_documented_filter_and_headers():
    """К-2 п.1 (сверка с документацией Kaspi, 22.11): фильтр даты — filter[orders][creationDate][$ge] в миллисекундах;
    заголовки — X-Auth-Token и JSON:API Content-Type."""
    import httpx

    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["headers"] = dict(request.headers)
        return httpx.Response(200, json={"data": []})

    client = KaspiClient(VALID_TOKEN, transport=httpx.MockTransport(handler), sleep=lambda s: None, min_interval=0)
    try:
        client.list_orders(1_700_000_000_000, 1)
    finally:
        client.close()
    assert "filter%5Borders%5D%5BcreationDate%5D%5B%24ge%5D=1700000000000" in seen["url"] or \
        "filter[orders][creationDate][$ge]=1700000000000" in seen["url"], seen["url"]
    assert seen["headers"]["x-auth-token"] == VALID_TOKEN
    assert seen["headers"]["content-type"] == "application/vnd.api+json"


def test_price_list_header_matches_kaspi_docs_and_bad_sku_is_skipped_with_note(client, demo, kaspi_on, mock):
    """Прайс по документации Kaspi (сверка 22.11): корень в пространстве kaspiShopping с схемой; sku — латиница и цифры
    до 20 знаков. Неподходящий артикул в файл не попадает, а в комментарии файла указывается, что его не передали."""
    _connect(client, demo)
    mock.generate(10, now=datetime.now(timezone.utc), products=3)
    client.post(f"/v1/shops/{demo['shop_id']}/kaspi/sync", headers=demo["headers"])
    with DbSession(engine) as db:
        db.add(Product(shop_id=demo["shop_id"], sku="Артикул-кириллица", name="Плохой артикул"))
        db.commit()
    with DbSession(engine) as db:  # товар с плохим артикулом должен иметь продажу, чтобы попасть в прайс
        from app.models import OrderItem as _OI
        bad = db.query(Product).filter(Product.sku == "Артикул-кириллица").one()
        ord_ = db.query(Order).filter(Order.shop_id == demo["shop_id"]).first()
        db.add(_OI(order_id=ord_.id, shop_id=demo["shop_id"], product_id=bad.id, qty=1, unit_price_minor=100000))
        db.commit()
    path = client.get(f"/v1/shops/{demo['shop_id']}/kaspi/connection", headers=demo["headers"]).json()["price_url"]
    body = client.get(path).content.decode("utf-8")
    assert body.lstrip().startswith("<?xml")
    assert 'xmlns="kaspiShopping"' in body and "xsi:schemaLocation" in body
    assert "ns0:" not in body
    assert "Артикул-кириллица" not in body.split("<!--")[0]  # не попал в файл как предложение
    assert "не переданы" in body and "Артикул-кириллица" in body  # но указан в комментарии


def test_sku_comes_from_product_links_not_from_entry_fields(client, demo, kaspi_on, mock):
    """К-6 п.1: в позиции заказа артикула нет; код берётся через orderentries → masterproducts → merchantProduct.
    Если связь не отдала код, позиция не теряется: её код строится из id (префикс KX-)."""
    _connect(client, demo)
    mock.generate(8, now=datetime.now(timezone.utc), days=5, products=3)
    r = client.post(f"/v1/shops/{demo['shop_id']}/kaspi/sync", headers=demo["headers"])
    assert r.status_code == 200, r.text
    from app.models import Product as _P
    with DbSession(engine) as db:
        skus = {p.sku for p in db.query(_P).filter(_P.shop_id == demo["shop_id"]).all()}
    kaspi_skus = {x for x in skus if x.startswith("K") and not x.startswith("KX-")}
    assert kaspi_skus and not {x for x in skus if x.startswith("KX-")}, skus


def test_partial_cancel_reduces_the_item_and_recalculates_net_sales(client, demo, kaspi_on, mock):
    """К-6 п.2: частичная отмена (orderPartialCancel) уменьшает количество в позиции после первой синхронизации.
    Выручка обзора и позиция заказа должны пересчитаться."""
    from app.models import OrderItem as _OI

    _connect(client, demo)
    mock.generate(9, now=datetime.now(timezone.utc), days=5, state_cycle=["COMPLETED"], products=3)
    client.post(f"/v1/shops/{demo['shop_id']}/kaspi/sync", headers=demo["headers"])

    def net() -> int:
        ov = client.get(f"/v1/shops/{demo['shop_id']}/overview?period=30d", headers=demo["headers"])
        return ov.json()["kpi"]["net_sales_minor"]

    # выбираем заказ с позицией из 2+ штук
    code = next(c for c, rows in mock.entries.items() if rows[0]["qty"] >= 2)
    old_qty = mock.entries[code][0]["qty"]
    price = mock.entries[code][0]["basePrice"]
    sku = f"K{mock.entries[code][0]['idx']}"

    def sold_of(sku_: str) -> int:
        from app.stock import stock_states
        from app.models import Shop as _Shop
        with DbSession(engine) as db:
            states = stock_states(db, db.get(_Shop, demo["shop_id"]))
            return next((st.sold_since for st in states.values() if st.sku == sku_), 0)

    # склад считает продажи от даты инвентаризации: ставим её на 10 дней назад, до всех заказов теста
    from app.models import Product as _Prod, StockMovement as _SM
    with DbSession(engine) as db:
        pid = db.query(_Prod.id).filter(_Prod.shop_id == demo["shop_id"], _Prod.sku == sku).scalar()
        db.add(_SM(id="inv" + pid[:20], shop_id=demo["shop_id"], product_id=pid, kind="inventory", qty=500,
                   occurred_at=datetime.now(timezone.utc) - timedelta(days=10)))
        db.commit()
    sold_before_stock = sold_of(sku)
    before = net()
    mock.partial_cancel(code, 0, 1)
    r = client.post(f"/v1/shops/{demo['shop_id']}/kaspi/sync", headers=demo["headers"])
    assert r.status_code == 200, r.text
    assert r.json()["items_changed"] >= 1
    with DbSession(engine) as db:
        order = db.query(Order).filter(Order.shop_id == demo["shop_id"], Order.number == code).one()
        items = db.query(_OI).filter(_OI.order_id == order.id).all()
        assert sum(it.qty for it in items) == sum(r_["qty"] for r_ in mock.entries[code])  # совпадает с Kaspi
    after = net()
    assert before - after == (old_qty - 1) * price * 100, (before, after, old_qty, price)  # цена в моке — тенге, в базе — тиын
    # склад: продажи того же товара уменьшились на отменённые штуки
    assert sold_before_stock - sold_of(sku) == old_qty - 1, (sold_before_stock, sold_of(sku))


def test_delisting_keeps_offer_with_available_no_and_zero_stock_when_store_codes_are_set(client, demo, kaspi_on, mock):
    """К-6 п.3: снятие с продажи — available="no" и stockCount="0" на всех складах, offer остаётся в файле.
    Без кодов складов наличие не передаётся: снятый товар не попадает в файл, и это записано в комментарии."""
    from app.models import Product as _Prod, ProductStock as _PS

    _connect(client, demo)
    mock.generate(9, now=datetime.now(timezone.utc), days=5, state_cycle=["COMPLETED"], products=3)
    client.post(f"/v1/shops/{demo['shop_id']}/kaspi/sync", headers=demo["headers"])
    sku = f"K{mock.entries[next(iter(mock.entries))][0]['idx']}"
    with DbSession(engine) as db:
        pid = db.query(_Prod.id).filter(_Prod.shop_id == demo["shop_id"], _Prod.sku == sku).scalar()
        db.add(_PS(id="ds" + pid[:20], shop_id=demo["shop_id"], product_id=pid, qty=0, delisted=True))
        db.commit()
    path = client.get(f"/v1/shops/{demo['shop_id']}/kaspi/connection", headers=demo["headers"]).json()["price_url"]

    # без кодов складов: товар вне файла, в комментарии — почему
    body = client.get(path).content.decode("utf-8")
    assert f'sku="{sku}"' not in body and "наличие не передаётся" in body

    # с кодом склада: товар в файле, наличие 0 и available="no"
    r = client.put(f"/v1/shops/{demo['shop_id']}/kaspi/stores", json={"store_ids": ["S-100"]}, headers=demo["headers"])
    assert r.status_code == 200, r.text
    assert r.json()["store_ids"] == ["S-100"]
    body = client.get(path).content.decode("utf-8")
    ns = "{kaspiShopping}"
    root = ET.fromstring(body.encode("utf-8"))
    offer = next(o for o in root.findall(f"./{ns}offers/{ns}offer") if o.get("sku") == sku)
    av = offer.find(f"{ns}availabilities/{ns}availability")
    assert av.get("available") == "no" and av.get("stockCount") == "0" and av.get("storeId") == "S-100"


def test_store_code_is_validated(client, demo, kaspi_on, mock):
    _connect(client, demo)
    r = client.put(f"/v1/shops/{demo['shop_id']}/kaspi/stores", json={"store_ids": ["bad code!"]}, headers=demo["headers"])
    assert r.status_code == 422 and r.json()["error"]["code"] == "kaspi_store_invalid"
