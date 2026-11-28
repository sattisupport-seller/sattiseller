"""К-37 п.3 и п.6: сводка прогона реального магазина — время загрузки по журналу и список «что сверить с кабинетом
Kaspi» по базе. Синтетические данные; скрипт только читает."""

import importlib.util
import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from tests.test_kaspi import _connect, kaspi_on, mock  # noqa: F401 — фикстуры

_spec = importlib.util.spec_from_file_location(
    "satti_kaspi_watch", Path(__file__).resolve().parent.parent / "scripts" / "kaspi_watch.py")
kw = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(kw)

NOW = datetime(2026, 11, 28, 12, 0, tzinfo=timezone.utc)


def _db() -> sqlite3.Connection:
    c = sqlite3.connect(":memory:")
    c.executescript("""
        create table shops (id text primary key, timezone text);
        create table orders (id text primary key, shop_id text, number text, status text, created_at text,
                             completed_at text, in_delivery_at text);
        create table order_items (id integer primary key, order_id text, shop_id text, product_id text, qty int,
                                  unit_price_minor int, buyer_delivery_minor int, commission_rate_bp int);
    """)
    c.execute("insert into shops values ('s1', 'Asia/Almaty')")
    rows = [  # номер, статус, дней назад, [(кол-во, цена ₸)]
        ("101", "completed", 1, [(1, 5_000)]),
        ("102", "cancelled", 2, [(2, 1_500)]),
        ("103", "returned", 3, [(1, 9_990)]),
        ("104", "in_progress", 0.1, [(1, 2_000)]),
        ("105", "completed", 10, [(3, 20_000)]),  # самый крупный
        ("106", "completed", 13, [(1, 700)]),  # самый ранний за 14 дней
        ("107", "completed", 20, [(1, 100_000)]),  # вне 14 дней — не в итоге
    ]
    for i, (num, st, days, items) in enumerate(rows):
        created = (NOW - timedelta(days=days)).replace(tzinfo=None).isoformat(sep=" ")
        c.execute("insert into orders values (?, 's1', ?, ?, ?, null, null)", (f"o{i}", num, st, created))
        for qty, price in items:
            c.execute("insert into order_items (order_id, shop_id, product_id, qty, unit_price_minor, "
                      "buyer_delivery_minor, commission_rate_bp) values (?, 's1', 'p', ?, ?, 0, null)",
                      (f"o{i}", qty, price * 100))
    return c


def test_check_list_picks_five_different_orders_and_totals_14_days():
    lines = kw.check_list(_db(), "s1", now=NOW)
    picked = [ln for ln in lines if ln.strip().startswith("№")]
    assert len(picked) == 5
    text = "\n".join(lines)
    for num in ("104", "101", "102", "103", "105"):  # самый новый, по исходу каждого вида, самый крупный
        assert f"№ {num}:" in text
    assert "№ 107" not in text
    total = next(ln for ln in lines if ln.startswith("Итог за 14 дней"))
    assert "заказов 6" in total
    assert "выдан 3 на 65 700 ₸" in total  # 5 000 + 60 000 + 700
    assert "отменён 1 на 3 000 ₸" in total
    assert "возврат 1 на 9 990 ₸" in total


def test_check_list_shows_shop_local_time():
    lines = kw.check_list(_db(), "s1", now=NOW)
    # № 101 создан 27.11 12:00 UTC → 17:00 в Алматы (UTC+5)
    assert any("№ 101: 27.11.2026 17:00, выдан, товары на 5 000 ₸" in ln for ln in lines)


def test_check_list_without_recent_orders():
    c = _db()
    c.execute("delete from orders")
    assert kw.check_list(c, "s1", now=NOW) == ["Заказов за 14 дней нет — сверять нечего."]


def test_load_timing_from_log():
    log = "\n".join([
        "2026-11-28 18:00:00,001 INFO uvicorn started",
        '2026-11-28 18:00:05,100 INFO httpx HTTP Request: GET https://kaspi.kz/shop/api/v2/orders?page[number]=0 "HTTP/1.1 200 OK"',
        "2026-11-28 18:01:15,000 INFO satti.kaspi kaspi observed shop=abcd1234 {...}",
        "2026-11-28 18:09:35,000 INFO satti.kaspi kaspi backfill done shop=abcd1234 orders=470",
    ])
    assert kw.load_timing(log) == {"first_numbers": 70.0, "full_load": 570.0}
    assert kw.load_timing("2026-11-28 18:00:00,001 INFO nothing") == {"first_numbers": None, "full_load": None}
    assert kw._fmt_delta(570) == "9 мин 30 с" and kw._fmt_delta(42) == "42 с"


def test_request_kind_keeps_collection_names():
    assert kw.request_kind("/shop/api/v2/orders?page[number]=0") == "orders"
    assert kw.request_kind("/shop/api/v2/orders/584110157/entries") == "orders/{id}/entries"
    assert kw.request_kind("/shop/api/v2/masterproducts/M0/merchantProduct") == "masterproducts/{id}/merchantProduct"
    assert kw.request_kind("/shop/api/v2/orderentries/abc123/product") == "orderentries/{id}/product"


def test_backfill_completion_is_logged(client, demo, kaspi_on, mock, caplog):  # noqa: F811
    mock.generate(120, now=datetime.now(timezone.utc), days=80, products=5)
    _connect(client, demo)
    with caplog.at_level(logging.INFO, logger="satti.kaspi"):
        r = client.post(f"/v1/shops/{demo['shop_id']}/kaspi/sync", headers=demo["headers"])
    assert r.status_code == 200, r.text
    done = [rec.getMessage() for rec in caplog.records if "kaspi backfill done" in rec.getMessage()]
    assert done and done[-1].endswith("orders=120")
    assert all("token" not in m.lower() for m in done)
