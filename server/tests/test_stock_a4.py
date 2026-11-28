"""К-33 А4: остатки в боевом режиме — инвариант прайса, «едет обратно», буфер, несколько складов, гонка."""

import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session as DbSession

from app.db import engine
from app.models import Product
from tests.kaspi_mock import DAY_MS
from tests.test_kaspi import (SELLER_NS, _connect, _import, _seller_xml, kaspi_on,  # noqa: F401
                              mock)

NS = f"{{{SELLER_NS}}}"


def _order(km, code, *, sku_idx=0, qty=1, state="ACCEPTED_BY_MERCHANT", handed_over=False, ago_h=0):
    created = int((datetime.now(timezone.utc) - timedelta(hours=ago_h)).timestamp() * 1000)
    km.entries[code] = [{"id": f"E{code}", "idx": sku_idx, "qty": qty, "basePrice": 5000}]
    attrs = {"state": state, "creationDate": created, "completedDate": None, "paymentMode": "PREPAID"}
    if handed_over:
        attrs["kaspiDelivery"] = {"courierTransmissionDate": created + 3_600_000}
    km.orders.append({"id": code, "type": "orders", "attributes": attrs,
                        "relationships": {"entries": {"links": {"related": f"/orders/{code}/entries"}}}})


def _set(km, code, **attrs):
    o = next(o for o in km.orders if o["id"] == code)
    o["attributes"].update(attrs)


def _sync(client, demo):
    r = client.post(f"/v1/shops/{demo['shop_id']}/kaspi/sync", headers=demo["headers"])
    assert r.status_code == 200, r.text


def _pid(demo, sku="K0"):
    with DbSession(engine) as db:
        return db.query(Product.id).filter(Product.shop_id == demo["shop_id"], Product.sku == sku).scalar()


def _stock(client, demo, pid):
    items = client.get(f"/v1/shops/{demo['shop_id']}/stock", headers=demo["headers"]).json()["items"]
    return next(i for i in items if i["productId"] == pid)


def _inventory(client, demo, pid, qty):
    assert client.put(f"/v1/shops/{demo['shop_id']}/products/{pid}/stock", headers=demo["headers"],
                      json={"qty": qty}).status_code == 200


def _setup(client, demo, km, stores=("S-100",)):
    _connect(client, demo)
    _order(km, "A-0", ago_h=48, state="COMPLETED")  # первая продажа — товар K0 появляется у нас
    _set(km, "A-0", completedDate=int(datetime.now(timezone.utc).timestamp() * 1000) - DAY_MS)
    _sync(client, demo)
    _import(client, demo, _seller_xml([("K0", "Товар 0", 5000), ("K1", "Товар 1", 3000)]))
    if stores:
        assert client.put(f"/v1/shops/{demo['shop_id']}/kaspi/stores", json={"store_ids": list(stores)},
                          headers=demo["headers"]).status_code == 200
    pid = _pid(demo)
    _inventory(client, demo, pid, 10)
    return pid


def _price(client, demo):
    url = client.get(f"/v1/shops/{demo['shop_id']}/kaspi/connection", headers=demo["headers"]).json()["price_url"]
    return client.get(url)


def _availability(resp, sku="K0"):
    root = ET.fromstring(resp.content)
    offer = next(o for o in root.iter(f"{NS}offer") if o.get("sku") == sku)
    return [(a.get("storeId"), a.get("available"), int(a.get("stockCount")))
            for a in offer.find(f"{NS}availabilities")]


# --- отмена до и после передачи в Kaspi Доставку (гид q3694) ----------------------------------------------------------

def test_cancel_before_handover_returns_stock_at_once(client, demo, kaspi_on, mock):  # noqa: F811
    pid = _setup(client, demo, mock)
    _order(mock, "B-1", qty=2)
    _sync(client, demo)
    assert _stock(client, demo, pid)["current"] == 8
    _set(mock, "B-1", state="CANCELLED")
    _sync(client, demo)
    row = _stock(client, demo, pid)
    assert row["current"] == 10 and row["returning"] == 0  # Kaspi вернул остаток сам — у нас так же


def test_cancel_after_handover_waits_for_pickup(client, demo, kaspi_on, mock):  # noqa: F811
    pid = _setup(client, demo, mock)
    _order(mock, "B-2", qty=3, handed_over=True)
    _sync(client, demo)
    _set(mock, "B-2", state="CANCELLED")
    _sync(client, demo)
    row = _stock(client, demo, pid)
    assert row["current"] == 7 and row["returning"] == 3  # едет обратно — в остаток не вернулся
    assert _availability(_price(client, demo)) == [("S-100", "yes", 7)]

    base = f"/v1/shops/{demo['shop_id']}/products/{pid}/stock/picked-up"
    assert client.post(base, headers=demo["headers"], json={"qty": 4, "sellable": True}).status_code == 422
    r = client.post(base, headers=demo["headers"], json={"qty": 2, "sellable": True})
    assert r.status_code == 200 and r.json() == {"current": 9, "returning": 1}
    r = client.post(base, headers=demo["headers"], json={"qty": 1, "sellable": False})  # брак — не в остаток
    assert r.json() == {"current": 9, "returning": 0}
    assert client.post(base, headers=demo["headers"], json={"qty": 1, "sellable": True}).status_code == 409


def test_partial_cancel_after_handover_also_travels_back(client, demo, kaspi_on, mock):  # noqa: F811
    pid = _setup(client, demo, mock)
    _order(mock, "B-3", qty=3, handed_over=True)
    _sync(client, demo)
    mock.partial_cancel("B-3", 0, 1)  # из 3 шт. осталась 1
    client.post(f"/v1/shops/{demo['shop_id']}/kaspi/sync?full=1", headers=demo["headers"])
    from app import kaspi as kaspi_service
    from app.models import KaspiConnection, Order
    with DbSession(engine) as db:  # позиции перечитываются суточной проверкой открытых заказов
        conn = db.get(KaspiConnection, demo["shop_id"])
        kaspi_service.refresh_open_orders(db, conn, kaspi_service.client_for(conn), datetime.now(timezone.utc))
        assert db.query(Order).filter(Order.number == "B-3").one().in_delivery_at is not None
    row = _stock(client, demo, pid)
    assert row["current"] == 7 and row["returning"] == 2


# --- буфер и несколько складов -----------------------------------------------------------------------------------------

def test_buffer_hides_units_and_delists_at_threshold(client, demo, kaspi_on, mock):  # noqa: F811
    pid = _setup(client, demo, mock)
    r = client.put(f"/v1/shops/{demo['shop_id']}/products/{pid}/stock/buffer", headers=demo["headers"],
                   json={"buffer": 3})
    assert r.status_code == 200 and r.json() == {"buffer": 3, "forSale": 7, "current": 10}
    assert _availability(_price(client, demo)) == [("S-100", "yes", 7)]
    _inventory(client, demo, pid, 3)
    assert _availability(_price(client, demo)) == [("S-100", "no", 0)]  # остаток не больше буфера — снят
    preview = client.get(f"/v1/shops/{demo['shop_id']}/stock/delist-preview", headers=demo["headers"]).json()
    assert any(i["productId"] == pid for i in preview["items"])


def test_many_stores_never_sum_above_stock(client, demo, kaspi_on, mock):  # noqa: F811
    _setup(client, demo, mock, stores=("S-1", "S-2", "S-3"))
    av = _availability(_price(client, demo))
    assert av == [("S-1", "yes", 10), ("S-2", "no", 0), ("S-3", "no", 0)]
    assert sum(q for _s, _a, q in av) <= 10


# --- инвариант: заказ между синхронизацией и запросом прайса -------------------------------------------------------

def test_order_between_sync_and_price_request_is_counted(client, demo, kaspi_on, mock):  # noqa: F811
    _setup(client, demo, mock)
    assert _availability(_price(client, demo)) == [("S-100", "yes", 10)]
    _order(mock, "R-1", qty=2, ago_h=0)  # покупатель купил, мы ещё не синхронизировались
    assert _availability(_price(client, demo)) == [("S-100", "yes", 8)]  # прайс сам досинхронизировал заказы


def test_price_is_not_served_when_orders_cannot_be_refreshed(client, demo, kaspi_on, mock):  # noqa: F811
    _setup(client, demo, mock)
    mock.list_requests = 0
    mock.fail_list_from = 1  # Kaspi не отвечает
    r = _price(client, demo)
    mock.fail_list_from = None
    assert r.status_code == 503 and r.headers["Retry-After"] == "600"  # не отдаём устаревший остаток


def test_invariant_over_mixed_events(client, demo, kaspi_on, mock):  # noqa: F811
    """Сумма по складам ≤ остаток − все известные заказы − едет обратно − буфер, после каждого события."""
    pid = _setup(client, demo, mock, stores=("S-1", "S-2"))
    known_sold = 0
    in_transit = 0
    steps = [("new", "M-1", 1, False), ("new", "M-2", 2, True), ("cancel", "M-2", 2, True),
             ("new", "M-3", 1, False), ("cancel", "M-3", 1, False), ("new", "M-4", 3, True)]
    for kind, code, qty, handed in steps:
        if kind == "new":
            _order(mock, code, qty=qty, handed_over=handed, ago_h=0)
            known_sold += qty
        else:
            _set(mock, code, state="CANCELLED")
            known_sold -= qty
            if handed:
                in_transit += qty
        av = _availability(_price(client, demo))
        assert sum(q for _s, _a, q in av) <= 10 - known_sold - in_transit, (code, av)
        assert sum(q for _s, _a, q in av) == max(10 - known_sold - in_transit, 0)
    assert _stock(client, demo, pid)["returning"] == 2
