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
    assert stats["added"] == 250 and stats["pages"] >= 3  # этап 1 (7 дней) и догрузка 90 дней — страницами
    with DbSession(engine) as db:
        assert db.query(Product).filter(Product.shop_id == demo["shop_id"], Product.sku.like("K%")).count() == 100


def test_failure_in_the_middle_keeps_progress_and_resumes_without_duplicates(client, demo, kaspi_on, mock):
    _connect(client, demo)
    mock.generate(250, now=datetime.now(timezone.utc))
    mock.fail_on_page = 1
    r = client.post(f"/v1/shops/{demo['shop_id']}/kaspi/sync", headers=demo["headers"])
    assert r.status_code == 503
    saved = _count_kaspi_orders(demo["shop_id"])
    assert 0 < saved < 250  # сохранённые страницы остались
    with DbSession(engine) as db:
        conn = db.get(KaspiConnection, demo["shop_id"])
        # К-17.3: курсор двигается только после полного прохода; ошибка записана; догрузка продолжится со страницы
        assert conn.cursor_ms is not None and conn.last_error  # этап 1 (7 дней) завершён, курсор стоит
        assert conn.backfill_done is False and conn.backfill_page >= 1
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
    """К-6/К-7 п.2–3: частичная отмена (orderPartialCancel) уменьшает количество в позиции после первой синхронизации.
    Выручка и прибыль (позиции) пересчитываются; остаток склада растёт на отменённое; в журнале — движение «отмена»."""
    from app.models import OrderItem as _OI, Product as _Prod, StockMovement as _SM
    from app.stock import stock_states
    from app.models import Shop as _Shop

    _connect(client, demo)
    mock.generate(9, now=datetime.now(timezone.utc), days=5, state_cycle=["COMPLETED"], products=3)
    client.post(f"/v1/shops/{demo['shop_id']}/kaspi/sync", headers=demo["headers"])

    def net() -> int:
        ov = client.get(f"/v1/shops/{demo['shop_id']}/overview?period=30d", headers=demo["headers"])
        return ov.json()["kpi"]["net_sales_minor"]

    code = next(c for c, rows in mock.entries.items() if rows[0]["qty"] >= 2)
    old_qty = mock.entries[code][0]["qty"]
    price = mock.entries[code][0]["basePrice"]
    sku = f"K{mock.entries[code][0]['idx']}"

    def stock_now() -> int:
        with DbSession(engine) as db:
            states = stock_states(db, db.get(_Shop, demo["shop_id"]))
            return next(st.current for st in states.values() if st.sku == sku)

    # склад считает от инвентаризации, датированной на 10 дней назад (раньше всех заказов теста)
    with DbSession(engine) as db:
        pid = db.query(_Prod.id).filter(_Prod.shop_id == demo["shop_id"], _Prod.sku == sku).scalar()
        db.add(_SM(id="inv" + pid[:20], shop_id=demo["shop_id"], product_id=pid, kind="inventory", qty=500,
                   occurred_at=datetime.now(timezone.utc) - timedelta(days=10)))
        db.commit()
    before_net, before_stock = net(), stock_now()
    mock.partial_cancel(code, 0, 1)
    r = client.post(f"/v1/shops/{demo['shop_id']}/kaspi/sync", headers=demo["headers"])
    assert r.status_code == 200, r.text
    assert r.json()["items_changed"] >= 1
    with DbSession(engine) as db:
        order = db.query(Order).filter(Order.shop_id == demo["shop_id"], Order.number == code).one()
        items = db.query(_OI).filter(_OI.order_id == order.id).all()
        assert sum(it.qty for it in items) == sum(r_["qty"] for r_ in mock.entries[code])  # совпадает с Kaspi
        moves = db.query(_SM).filter(_SM.shop_id == demo["shop_id"], _SM.kind == "cancel", _SM.product_id == pid).all()
        assert [m.qty for m in moves] == [old_qty - 1]  # движение «отмена» на разницу
    assert before_net - net() == (old_qty - 1) * price * 100, "цифры в обзоре: цена в моке — тенге, в базе — тиын"
    assert stock_now() - before_stock == old_qty - 1, "остаток вырос ровно на отменённые штуки (без двойного учёта)"


def test_store_hint_comes_from_order_data_and_is_only_a_suggestion(client, demo, kaspi_on, mock):
    """К-7 п.1: код склада из данных заказов (связь позиции с пунктом выдачи) — только подсказка.
    Значение задаёт продавец; подсказка не подставляется сама."""
    _connect(client, demo)
    mock.generate(4, now=datetime.now(timezone.utc), days=5, products=2)
    client.post(f"/v1/shops/{demo['shop_id']}/kaspi/sync", headers=demo["headers"])
    view = client.get(f"/v1/shops/{demo['shop_id']}/kaspi/connection", headers=demo["headers"]).json()
    assert view["store_hint"] == "PP1" and view["store_ids"] == []


def test_store_code_is_validated(client, demo, kaspi_on, mock):
    _connect(client, demo)
    r = client.put(f"/v1/shops/{demo['shop_id']}/kaspi/stores", json={"store_ids": ["bad code!"]}, headers=demo["headers"])
    assert r.status_code == 422 and r.json()["error"]["code"] == "kaspi_store_invalid"


# ---------- прайс продавца (К-16.3): импорт, ссылка только после импорта, наш файл = каталог продавца ----------

SELLER_NS = "kaspiShopping"


def _seller_xml(offers, date_attr="2020-01-01") -> bytes:
    """Прайс в формате кабинета Kaspi: offers — список (sku, название, цена тенге)."""
    items = "".join(
        f'<offer sku="{sku}"><model>{name}</model><price>{price}</price></offer>' for sku, name, price in offers)
    xml = (f'<?xml version="1.0" encoding="UTF-8"?>'
           f'<kaspi_catalog date="{date_attr}" xmlns="{SELLER_NS}" '
           f'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
           f'xsi:schemaLocation="{SELLER_NS} http://kaspi.kz/kaspishopping.xsd">'
           f'<company>Магазин</company><merchantid>S-1</merchantid><offers>{items}</offers></kaspi_catalog>')
    return xml.encode("utf-8")


def _import(client, demo, data: bytes):
    return client.post(f"/v1/shops/{demo['shop_id']}/kaspi/catalog", headers=demo["headers"],
                       files={"file": ("price.xml", data, "application/xml")})


def _price_key(demo) -> str:
    with DbSession(engine) as db:
        return db.get(KaspiConnection, demo["shop_id"]).price_key


def test_price_link_is_hidden_until_seller_catalog_is_imported(client, demo, kaspi_on, mock):
    _connect(client, demo)
    view = client.get(f"/v1/shops/{demo['shop_id']}/kaspi/connection", headers=demo["headers"]).json()
    assert view["price_url"] is None and view["catalog"] is None
    assert "Сначала загрузите прайс-лист" in view["price_hint"]
    r = client.get(f"/v1/kaspi/price/{demo['shop_id']}/{_price_key(demo)}")
    assert r.status_code == 409 and r.json()["error"]["code"] == "catalog_not_imported"


def test_our_file_keeps_the_whole_seller_catalog_and_prices(client, demo, kaspi_on, mock):
    """Наш файл — весь каталог продавца с его ценами; товары и цены не меняются, добавляется только наличие по складу."""
    _connect(client, demo)
    mock.generate(20, now=datetime.now(timezone.utc), days=5, products=5)
    client.post(f"/v1/shops/{demo['shop_id']}/kaspi/sync", headers=demo["headers"])
    offers = [("K0", "Товар 0", 1111), ("K1", "Товар 1", 2222), ("SELLER-ONLY", "Не продаётся в заказах", 3333)]
    r = _import(client, demo, _seller_xml(offers))
    assert r.status_code == 200, r.text
    assert r.json()["catalog"]["offers_count"] == 3 and r.json()["price_url"]
    body = client.get(r.json()["price_url"]).content
    root = ET.fromstring(body)
    got = {o.get("sku"): o for o in root.iter(f"{{{SELLER_NS}}}offer")}
    assert set(got) == {"K0", "K1", "SELLER-ONLY"}  # весь каталог, не только проданное
    assert got["SELLER-ONLY"].find(f"{{{SELLER_NS}}}price").text == "3333"  # цена продавца не изменена
    assert got["K0"].find(f"{{{SELLER_NS}}}model").text == "Товар 0"


def test_price_file_keeps_seller_namespace_and_refreshes_date(client, demo, kaspi_on, mock):
    _connect(client, demo)
    _import(client, demo, _seller_xml([("A1", "Тест", 500)], date_attr="2020-01-01"))
    body = client.get(client.get(f"/v1/shops/{demo['shop_id']}/kaspi/connection", headers=demo["headers"]).json()["price_url"]).content.decode("utf-8")
    assert 'xmlns="kaspiShopping"' in body and "ns0:" not in body and "xsi:schemaLocation" in body
    assert 'date="2020-01-01"' not in body


def test_import_refuses_files_with_dtd_or_wrong_root(client, demo, kaspi_on, mock):
    _connect(client, demo)
    bomb = b'<?xml version="1.0"?><!DOCTYPE kaspi_catalog [<!ENTITY a "x">]><kaspi_catalog><offers/></kaspi_catalog>'
    assert _import(client, demo, bomb).status_code == 422
    assert _import(client, demo, b"<html><body>no</body></html>").status_code == 422
    assert _import(client, demo, b"<kaspi_catalog><offers></offers></kaspi_catalog>").status_code == 422


def test_delisting_keeps_offer_with_available_no_and_zero_stock_when_store_codes_are_set(client, demo, kaspi_on, mock):
    """Снятие с продажи — available="no" и stockCount="0" на складе; без кодов складов файл продавца не меняется."""
    from app.models import Product as _Prod, ProductStock as _PS

    _connect(client, demo)
    mock.generate(9, now=datetime.now(timezone.utc), days=5, state_cycle=["COMPLETED"], products=3)
    client.post(f"/v1/shops/{demo['shop_id']}/kaspi/sync", headers=demo["headers"])
    _import(client, demo, _seller_xml([("K0", "Товар 0", 1000), ("K1", "Товар 1", 2000)]))
    with DbSession(engine) as db:
        pid = db.query(_Prod.id).filter(_Prod.shop_id == demo["shop_id"], _Prod.sku == "K0").scalar()
        db.add(_PS(id="ds" + pid[:20], shop_id=demo["shop_id"], product_id=pid, qty=0, delisted=True))
        db.commit()
    url = client.get(f"/v1/shops/{demo['shop_id']}/kaspi/connection", headers=demo["headers"]).json()["price_url"]
    body = client.get(url).content.decode("utf-8")
    assert "снятие с продажи не передано" in body  # без кодов складов — записано в комментарии
    r = client.put(f"/v1/shops/{demo['shop_id']}/kaspi/stores", json={"store_ids": ["S-100"]}, headers=demo["headers"])
    assert r.status_code == 200
    root = ET.fromstring(client.get(url).content)
    offer = next(o for o in root.iter(f"{{{SELLER_NS}}}offer") if o.get("sku") == "K0")
    av = offer.find(f"{{{SELLER_NS}}}availabilities/{{{SELLER_NS}}}availability")
    assert av.get("available") == "no" and av.get("stockCount") == "0" and av.get("storeId") == "S-100"
    assert offer.find(f"{{{SELLER_NS}}}price").text == "1000"  # цена не меняется даже при снятии


def test_product_gets_name_and_category_from_kaspi(client, demo, kaspi_on, mock):
    """К-16.1/К-16.2: название товара — из связи товара Kaspi (не артикул); категория — из позиции (для комиссии)."""
    from app.models import Product as _P

    _connect(client, demo)
    mock.generate(4, now=datetime.now(timezone.utc), days=5, products=2)
    client.post(f"/v1/shops/{demo['shop_id']}/kaspi/sync", headers=demo["headers"])
    with DbSession(engine) as db:
        p = db.query(_P).filter(_P.shop_id == demo["shop_id"], _P.sku == "K0").one()
        assert p.name == "Товар K0 из кабинета"
        assert p.category == "Посуда для кухни"


def test_placeholder_name_is_replaced_on_next_sync(client, demo, kaspi_on, mock):
    """Товар, созданный раньше с названием-артикулом, получает название Kaspi при следующей синхронизации."""
    from app.models import Product as _P

    _connect(client, demo)
    mock.generate(2, now=datetime.now(timezone.utc), days=5, products=1)
    client.post(f"/v1/shops/{demo['shop_id']}/kaspi/sync", headers=demo["headers"])
    with DbSession(engine) as db:
        p = db.query(_P).filter(_P.shop_id == demo["shop_id"], _P.sku == "K0").one()
        p.name = "K0"  # имитация старого товара
        p.category = "Без категории"
        db.commit()
    mock.generate(1, now=datetime.now(timezone.utc), days=1, products=1)
    client.post(f"/v1/shops/{demo['shop_id']}/kaspi/sync", headers=demo["headers"])
    with DbSession(engine) as db:
        p = db.query(_P).filter(_P.shop_id == demo["shop_id"], _P.sku == "K0").one()
        assert p.name == "Товар K0 из кабинета" and p.category == "Посуда для кухни"


def test_product_card_asks_to_check_commission_when_category_has_no_rate(client, demo, kaspi_on, mock):
    from datetime import date as _date
    from app.models import CommissionPreset as _CP, Product as _P

    _connect(client, demo)
    mock.generate(2, now=datetime.now(timezone.utc), days=5, products=1)
    client.post(f"/v1/shops/{demo['shop_id']}/kaspi/sync", headers=demo["headers"])
    with DbSession(engine) as db:
        pid = db.query(_P.id).filter(_P.shop_id == demo["shop_id"], _P.sku == "K0").scalar()
    url = f"/v1/shops/{demo['shop_id']}/products/{pid}"
    r = client.get(url, headers=demo["headers"])
    assert r.status_code == 200 and "уточнить комиссию" in r.json()["commission_note"]
    with DbSession(engine) as db:
        db.add(_CP(shop_id=demo["shop_id"], category="Посуда для кухни", rate_bp=1200, effective_from=_date(2020, 1, 1),
                   source="manual", verified=True))
        db.commit()
    assert client.get(url, headers=demo["headers"]).json()["commission_note"] is None


def test_second_sync_while_one_runs_is_refused(client, demo, kaspi_on, mock):
    """К-17.3: параллельная синхронизация того же магазина не запускается (409), а не идёт второй раз."""
    from app import kaspi as kaspi_service

    _connect(client, demo)
    mock.generate(3, now=datetime.now(timezone.utc), days=5, products=1)
    lock = kaspi_service._SHOP_LOCKS.setdefault(demo["shop_id"], __import__("threading").Lock())
    assert lock.acquire(blocking=False)
    try:
        r = client.post(f"/v1/shops/{demo['shop_id']}/kaspi/sync", headers=demo["headers"])
        assert r.status_code == 409 and r.json()["error"]["code"] == "kaspi_sync_running"
    finally:
        lock.release()
    assert client.post(f"/v1/shops/{demo['shop_id']}/kaspi/sync", headers=demo["headers"]).status_code == 200


def test_first_load_is_queued_to_background_when_scheduler_runs(client, demo, kaspi_on, mock, monkeypatch):
    """К-17.3: первая загрузка в продакшене (планировщик включён) не держит HTTP-запрос: ставится в очередь."""
    _connect(client, demo)
    mock.generate(5, now=datetime.now(timezone.utc), days=5, products=1)
    monkeypatch.setenv("SATTI_SCHEDULER", "1")
    r = client.post(f"/v1/shops/{demo['shop_id']}/kaspi/sync", headers=demo["headers"])
    assert r.status_code == 200 and r.json()["status"] == "queued"
    assert _count_kaspi_orders(demo["shop_id"]) == 0  # в запросе заказы не загружаются
    with DbSession(engine) as db:
        conn = db.get(KaspiConnection, demo["shop_id"])
        assert conn.cursor_ms is None and conn.last_sync_at is None  # due для планировщика
    monkeypatch.delenv("SATTI_SCHEDULER")
    assert client.post(f"/v1/shops/{demo['shop_id']}/kaspi/sync", headers=demo["headers"]).json()["added"] == 5


def test_overview_says_when_period_is_older_than_kaspi_history(client, demo, kaspi_on, mock):
    """К-17.3: период старше 90 дней загрузки Kaspi — в обзоре честная пометка о неполных данных."""
    _connect(client, demo)
    mock.generate(2, now=datetime.now(timezone.utc), days=5, products=1)
    client.post(f"/v1/shops/{demo['shop_id']}/kaspi/sync", headers=demo["headers"])
    r = client.get(f"/v1/shops/{demo['shop_id']}/overview?period=2025-12-01..2026-11-22", headers=demo["headers"])
    assert r.status_code == 200
    assert r.json()["history_note"] and "неполные" in r.json()["history_note"]
    r = client.get(f"/v1/shops/{demo['shop_id']}/overview?period=7d", headers=demo["headers"])
    assert r.json()["history_note"] is None


def test_seller_delivery_is_an_expense_and_credit_orders_use_installment_rate(client, demo, kaspi_on, mock):
    """К-17.3: доставка, которую оплачивает продавец (deliveryCostForSeller), — расход заказа; нет поля — 0.
    К-18 (заменило К-17): рассрочка (PAY_WITH_CREDIT) — комиссия по тарифу рассрочки продавца, прибыль считается."""
    from app.models import OrderItem as _OI

    _connect(client, demo)
    mock.generate(8, now=datetime.now(timezone.utc), days=5, products=2)
    client.post(f"/v1/shops/{demo['shop_id']}/kaspi/sync", headers=demo["headers"])
    with DbSession(engine) as db:
        delivery_order = db.query(Order).filter(Order.shop_id == demo["shop_id"], Order.number == "KC00000000").one()
        first_item = db.query(_OI).filter(_OI.order_id == delivery_order.id).first()
        assert first_item.buyer_delivery_minor == 50_000  # 500 тенге на первой позиции
        credit_order = db.query(Order).filter(Order.shop_id == demo["shop_id"], Order.number == "KC00000001").one()
        items = db.query(_OI).filter(_OI.order_id == credit_order.id).all()
        assert items and all(it.buyer_delivery_minor == 0 for it in items)  # без поля доставки — 0 (К-30)
        assert all(it.commission_rate_bp == 1090 for it in items)  # рассрочка — тариф 10,9 % (К-18)
        plain = db.query(Order).filter(Order.shop_id == demo["shop_id"], Order.number == "KC00000002").one()
        assert all(it.buyer_delivery_minor == 0 for it in db.query(_OI).filter(_OI.order_id == plain.id).all()[1:])


# ---------- окно возврата 14 дней от выдачи (К-19) ----------

def _pick_code(mock):
    """Заказ, у которого первая позиция больше одной штуки (чтобы частичная отмена что-то меняла)."""
    return next(c for c, rows in mock.entries.items() if rows[0]["qty"] >= 2)


def _order_dates(mock, code, created_days_ago, delivered_days_ago):
    """Заказ с датой создания и выдачи относительно сейчас (мок)."""
    now = datetime.now(timezone.utc)
    for o in mock.orders:
        if o["id"] == code:
            o["attributes"]["creationDate"] = int((now - timedelta(days=created_days_ago)).timestamp() * 1000)
            o["attributes"]["completedDate"] = int((now - timedelta(days=delivered_days_ago)).timestamp() * 1000)
            o["attributes"]["state"] = "COMPLETED"
            return
    raise KeyError(code)


def _sync_and_open_refresh(client, demo, mock):
    from app import kaspi as kaspi_service
    from app.kaspi_client import KaspiClient as _KC
    from app.models import KaspiConnection as _KCon

    client.post(f"/v1/shops/{demo['shop_id']}/kaspi/sync", headers=demo["headers"])
    with DbSession(engine) as db:
        conn = db.get(_KCon, demo["shop_id"])
        kc = _KC(VALID_TOKEN, transport=mock.transport(), sleep=lambda s: None, min_interval=0)
        return kaspi_service.refresh_open_orders(db, conn, kc, datetime.now(timezone.utc))


def _entry_qty_sum(code):
    from app.models import OrderItem as _OI
    with DbSession(engine) as db:
        order = db.query(Order).filter(Order.number == code).one()
        return sum(it.qty for it in db.query(_OI).filter(_OI.order_id == order.id).all())


def test_return_on_day_13_after_delivery_is_still_tracked_though_created_20_days_ago(client, demo, kaspi_on, mock):
    """К-19: окно возврата — 14 дней от выдачи. Создан 20 дней назад, выдан 13 дней назад: заказ ещё отслеживается."""
    _connect(client, demo)
    mock.generate(3, now=datetime.now(timezone.utc), days=5, state_cycle=["COMPLETED"], products=2)
    code = _pick_code(mock)
    _order_dates(mock, code, created_days_ago=20, delivered_days_ago=13)
    total_before = sum(r["qty"] for r in mock.entries[code])
    _sync_and_open_refresh(client, demo, mock)
    assert _entry_qty_sum(code) == total_before
    old_qty = mock.entries[code][0]["qty"]
    mock.partial_cancel(code, 0, 1)  # возврат/отмена на 13-й день
    res = _sync_and_open_refresh(client, demo, mock)
    assert res["checked"] >= 1 and res["items_changed"] >= 1
    assert _entry_qty_sum(code) == total_before - (old_qty - 1)


def test_return_window_closes_17_days_after_delivery(client, demo, kaspi_on, mock):
    """К-19: через 14 дней + 3 дня запаса после выдачи заказ больше не перечитывается."""
    _connect(client, demo)
    mock.generate(3, now=datetime.now(timezone.utc), days=5, state_cycle=["COMPLETED"], products=2)
    code = _pick_code(mock)
    _order_dates(mock, code, created_days_ago=30, delivered_days_ago=18)
    total_before = sum(r["qty"] for r in mock.entries[code])
    _sync_and_open_refresh(client, demo, mock)
    mock.partial_cancel(code, 0, 1)
    _sync_and_open_refresh(client, demo, mock)
    assert _entry_qty_sum(code) == total_before  # окно закрыто: изменение не подхватываем


def test_undelivered_order_is_tracked_regardless_of_creation_date(client, demo, kaspi_on, mock):
    """К-19: невыданный заказ (в пути) отслеживается до выдачи, даже если создан давно."""
    _connect(client, demo)
    mock.generate(3, now=datetime.now(timezone.utc), days=5, state_cycle=["COMPLETED"], products=2)
    code = _pick_code(mock)
    _order_dates(mock, code, created_days_ago=60, delivered_days_ago=0)
    for o in mock.orders:
        if o["id"] == code:
            o["attributes"]["state"] = "ACCEPTED_BY_MERCHANT"
            o["attributes"]["completedDate"] = None
    total_before = sum(r["qty"] for r in mock.entries[code])
    _sync_and_open_refresh(client, demo, mock)
    old_qty = mock.entries[code][0]["qty"]
    mock.partial_cancel(code, 0, 1)
    _sync_and_open_refresh(client, demo, mock)
    assert _entry_qty_sum(code) == total_before - (old_qty - 1)


def test_nightly_job_refreshes_open_orders_for_active_connections(client, demo, kaspi_on, mock, monkeypatch):
    from app import scheduler as sched
    from app.kaspi_client import KaspiClient as _KC

    _connect(client, demo)
    mock.generate(2, now=datetime.now(timezone.utc), days=5, products=1)
    client.post(f"/v1/shops/{demo['shop_id']}/kaspi/sync", headers=demo["headers"])
    monkeypatch.setattr("app.kaspi.client_for", lambda conn: _KC(VALID_TOKEN, transport=mock.transport(),
                                                                sleep=lambda s: None, min_interval=0))
    done = sched.run_kaspi_nightly_reread()
    assert (demo["shop_id"], "refreshed") in done



def test_installment_orders_use_seller_installment_rate(client, demo, kaspi_on, mock):
    """К-18: рассрочка — комиссия по тарифу рассрочки (по умолчанию 10,9%, продавец может изменить); прибыль считается."""
    from app.models import CommissionPreset as _CP, OrderItem as _OI
    from app import kaspi as kaspi_service

    _connect(client, demo)
    mock.generate(8, now=datetime.now(timezone.utc), days=5, products=2)
    client.post(f"/v1/shops/{demo['shop_id']}/kaspi/sync", headers=demo["headers"])
    with DbSession(engine) as db:
        credit = db.query(Order).filter(Order.shop_id == demo["shop_id"], Order.number == "KC00000001").one()
        items = db.query(_OI).filter(_OI.order_id == credit.id).all()
        assert items and all(it.commission_rate_bp == 1090 for it in items)  # 10,9% по умолчанию
        plain = db.query(Order).filter(Order.shop_id == demo["shop_id"], Order.number == "KC00000002").one()
        assert all(it.commission_rate_bp is None for it in db.query(_OI).filter(_OI.order_id == plain.id).all())
        db.add(_CP(shop_id=demo["shop_id"], category=kaspi_service.INSTALLMENT_CATEGORY, rate_bp=1350,
                   effective_from=None, source="manual", verified=False))
        db.commit()
    mock.generate(8, now=datetime.now(timezone.utc), days=3, products=2)
    client.post(f"/v1/shops/{demo['shop_id']}/kaspi/sync", headers=demo["headers"])
    with DbSession(engine) as db:
        new_credit = [o for o in db.query(Order).filter(Order.shop_id == demo["shop_id"]).all()
                      if o.number.startswith("KC") and o.number not in ("KC00000001",)]
        rates = {it.commission_rate_bp for o in new_credit for it in db.query(_OI).filter(_OI.order_id == o.id).all()}
        assert 1350 in rates  # новые заказы в рассрочку — по новой ставке продавца


def test_first_load_shows_progress_and_completes_90_days(client, demo, kaspi_on, mock):
    """К-18.3: прогресс «загружено N из M»; после первой загрузки — полные 90 дней, прогресс завершён."""
    _connect(client, demo)
    mock.generate(120, now=datetime.now(timezone.utc), days=60, products=5)
    client.post(f"/v1/shops/{demo['shop_id']}/kaspi/sync", headers=demo["headers"])
    load = client.get(f"/v1/shops/{demo['shop_id']}/kaspi/connection", headers=demo["headers"]).json()["load"]
    assert load["complete"] is True
    assert load["done"] == 120 and load["total"] == 120
    assert _count_kaspi_orders(demo["shop_id"]) == 120


def test_first_seven_days_are_loaded_before_the_rest(client, demo, kaspi_on, mock):
    """К-18.3: если догрузка оборвалась, заказы последних 7 дней уже есть — продавец видит данные."""
    _connect(client, demo)
    mock.generate(250, now=datetime.now(timezone.utc), days=60, products=5)
    mock.fail_on_page = 1  # первая страница этапа 2 падает
    client.post(f"/v1/shops/{demo['shop_id']}/kaspi/sync", headers=demo["headers"])
    recent = datetime.now(timezone.utc) - timedelta(days=7)
    with DbSession(engine) as db:
        from app.models import Order as _O
        newest = db.query(_O).filter(_O.shop_id == demo["shop_id"], _O.created_at >= recent).count()
    assert newest >= 1
    mock.fail_on_page = None


def test_main_scenario_first_day_connect_import_costs_profit_by_product(client, demo, kaspi_on, mock):
    """Главный сценарий владельца (К-18): подключение → прайс продавца → продажи за 90 дней → себестоимость →
    прибыль по товарам за 90 дней (комиссия категории, Kaspi Доставка) → убыточные сверху → подсказка о себестоимости."""
    from app.models import CommissionPreset as _CP, Product as _P

    _connect(client, demo)
    xml = _seller_xml([("K0", "Товар 0", 1000), ("K1", "Товар 1", 1000), ("K2", "Товар 2", 1000),
                       ("K3", "Товар 3", 1000), ("K4", "Товар 4", 1000)])
    assert _import(client, demo, xml).status_code == 200
    mock.generate(40, now=datetime.now(timezone.utc), days=85, state_cycle=["COMPLETED"], products=5)
    sync = client.post(f"/v1/shops/{demo['shop_id']}/kaspi/sync", headers=demo["headers"]).json()
    assert sync["added"] == 40
    load = client.get(f"/v1/shops/{demo['shop_id']}/kaspi/connection", headers=demo["headers"]).json()["load"]
    assert load["complete"] is True  # 90 дней загружены
    with DbSession(engine) as db:
        db.add(_CP(shop_id=demo["shop_id"], category="Посуда для кухни", rate_bp=1200, effective_from=None,
                   source="manual", verified=True))
        db.commit()
        pids = {p.sku: p.id for p in db.query(_P).filter(_P.shop_id == demo["shop_id"]).all()}
    # себестоимость: K0 — прибыль, K1 — убыток, K2..K4 — без себестоимости
    for sku, purchase in (("K0", "300"), ("K1", "5000")):
        r = client.post(f"/v1/shops/{demo['shop_id']}/products/{pids[sku]}/cost-versions", headers=demo["headers"],
                        json={"purchase": purchase, "apply_to_history": True})
        assert r.status_code == 201, r.text
    rows = client.get(f"/v1/shops/{demo['shop_id']}/products?period=90d", headers=demo["headers"]).json()
    items = rows["items"]
    by_sku = {r_["sku"]: r_ for r_ in items}
    # подсказка: сколько продаваемых товаров без себестоимости (в демо-магазине есть и свои товары)
    assert rows["no_cost_count"] >= 3
    assert by_sku["K2"]["profit_minor"] is None and by_sku["K3"]["profit_minor"] is None  # не ноль
    assert by_sku["K0"]["profit_minor"] > 0 and by_sku["K1"]["profit_minor"] < 0
    # убыточные сверху: известная прибыль идёт от меньшей к большей
    known = [r_["profit_minor"] for r_ in items if r_["profit_minor"] is not None]
    assert known == sorted(known)
    assert known[0] < 0
