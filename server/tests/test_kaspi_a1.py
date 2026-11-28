"""К-33 А1: подключение реального магазина — только чтение, окна по 14 дней, 90 дней с продолжением после обрыва,
странные данные не роняют загрузку, замер на синтетическом магазине (500 товаров, 3 000 заказов за 90 дней)."""

import inspect
import re
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session as DbSession

from app import kaspi as kaspi_service
from app import kaspi_client
from app.db import engine
from app.kaspi_client import KaspiClient
from app.models import KaspiConnection, Order, Shop
from tests.kaspi_mock import DAY_MS, VALID_TOKEN, MockKaspi
from tests.test_kaspi import _connect, _count_kaspi_orders, kaspi_on, mock  # noqa: F401 — фикстуры


def _sync(client, demo):
    return client.post(f"/v1/shops/{demo['shop_id']}/kaspi/sync", headers=demo["headers"])


def _numbers(shop_id):
    with DbSession(engine) as db:
        return [n for (n,) in db.query(Order.number).filter(Order.shop_id == shop_id, Order.number.like("KC%"))]


# --- только чтение ---------------------------------------------------------------------------------------------------

def test_kaspi_client_has_only_get_requests_in_code():
    """В коде клиента Kaspi нет ни одного запроса, который меняет данные (заказы, цены) в кабинете продавца."""
    src = inspect.getsource(kaspi_client)
    assert not re.search(r"\.(post|put|patch|delete)\(", src)
    assert not re.search(r"method\s*=\s*['\"](POST|PUT|PATCH|DELETE)", src, re.I)
    assert "self._http.get(" in src


def test_full_connect_and_sync_sends_only_get(client, demo, kaspi_on, mock):  # noqa: F811
    mock.generate(300, now=datetime.now(timezone.utc), days=85, products=20)
    assert _connect(client, demo).status_code == 201
    assert _sync(client, demo).status_code == 200
    client.post(f"/v1/shops/{demo['shop_id']}/kaspi/sync", headers=demo["headers"])
    methods = {m for m, _ in mock.methods_seen}
    assert methods == {"GET"}, methods


# --- окна по 14 дней и 90 дней ---------------------------------------------------------------------------------------

def test_windows_are_at_most_14_days_and_cover_the_period():
    since, until = 0, 90 * DAY_MS
    ws = kaspi_service._windows(since, until)
    assert ws[0][0] == since and ws[-1][1] == until
    for (a, b), nxt in zip(ws, ws[1:] + [None]):
        assert b - a <= 14 * DAY_MS
        if nxt:
            assert nxt[0] == b + 1  # без дыр и наложений


def test_backfill_windows_newest_first_and_stop_at_90_days():
    now = 1_000 * DAY_MS
    ws = kaspi_service._backfill_windows(now)
    assert ws[0][1] == now - 14 * DAY_MS - 1
    assert ws[-1][0] == now - 90 * DAY_MS
    assert all(ws[i][0] > ws[i + 1][0] for i in range(len(ws) - 1))


def test_90_days_load_never_asks_more_than_14_days(client, demo, kaspi_on, mock):  # noqa: F811
    mock.generate(600, now=datetime.now(timezone.utc), days=89, products=30)
    _connect(client, demo)
    r = _sync(client, demo)
    assert r.status_code == 200, r.text
    assert mock.bad_period_requests == 0
    nums = _numbers(demo["shop_id"])
    assert len(nums) == 600 == len(set(nums))
    load = client.get(f"/v1/shops/{demo['shop_id']}/kaspi/connection", headers=demo["headers"]).json()["load"]
    assert load == {"done": 600, "total": 600, "complete": True}


def test_regular_sync_after_long_pause_is_split_into_windows(client, demo, kaspi_on, mock):  # noqa: F811
    """Курсор месячной давности: «курсор − 14 дней … сейчас» = 44 дня — Kaspi так не отдаёт; идём окнами."""
    now = datetime.now(timezone.utc)
    mock.generate(50, now=now, days=80)
    _connect(client, demo)
    assert _sync(client, demo).status_code == 200
    with DbSession(engine) as db:
        conn = db.get(KaspiConnection, demo["shop_id"])
        conn.cursor_ms = int((now - timedelta(days=30)).timestamp() * 1000)
        db.commit()
    mock.bad_period_requests = 0
    assert _sync(client, demo).status_code == 200
    assert mock.bad_period_requests == 0


def test_backfill_resumes_after_failure_without_duplicates(client, demo, kaspi_on, mock):  # noqa: F811
    mock.generate(900, now=datetime.now(timezone.utc), days=89, products=10)
    _connect(client, demo)
    mock.fail_list_from = 6  # первая загрузка прошла, догрузка оборвалась на одном из окон
    assert _sync(client, demo).status_code == 503
    first = len(_numbers(demo["shop_id"]))
    with DbSession(engine) as db:
        conn = db.get(KaspiConnection, demo["shop_id"])
        assert conn.backfill_done is False and conn.backfill_page > 0 and conn.last_error
        assert conn.cursor_ms is not None  # последние 14 дней уже загружены — продавец видит первые цифры
    assert 0 < first < 900
    mock.fail_list_from = None
    assert _sync(client, demo).status_code == 200
    nums = _numbers(demo["shop_id"])
    assert len(nums) == 900 == len(set(nums))


def test_first_numbers_come_from_last_14_days(client, demo, kaspi_on, mock):  # noqa: F811
    now = datetime.now(timezone.utc)
    mock.generate(400, now=now, days=89)
    _connect(client, demo)
    mock.fail_list_from = 3  # этап 1 (одно окно 14 дней, 1–2 страницы) прошёл, дальше Kaspi упал
    _sync(client, demo)
    with DbSession(engine) as db:
        recent = db.query(Order).filter(Order.shop_id == demo["shop_id"], Order.number.like("KC%"),
                                        Order.created_at >= now - timedelta(days=14)).count()
        conn = db.get(KaspiConnection, demo["shop_id"])
        estimate = conn.load_total
    expected_recent = sum(1 for o in mock.orders
                          if o["attributes"]["creationDate"] >= int((now - timedelta(days=14)).timestamp() * 1000))
    assert recent == expected_recent
    assert estimate and 300 <= estimate <= 500  # оценка «из ~400» по первым 14 дням
    mock.fail_list_from = None


# --- странные данные --------------------------------------------------------------------------------------------------

def test_strange_orders_are_skipped_logged_and_explained(client, demo, kaspi_on, mock, caplog):  # noqa: F811
    mock.generate(30, now=datetime.now(timezone.utc), days=10)
    del mock.orders[3]["attributes"]["creationDate"]  # нет обязательного поля
    mock.orders[5]["attributes"]["creationDate"] = mock.orders[5]["attributes"]["creationDate"]  # норма
    mock.orders[7]["attributes"]["newFieldFromKaspi"] = {"x": [1, 2]}  # неизвестное поле — не мешает
    mock.entries[mock.orders[9]["id"]][0]["qty"] = "много"  # странное количество в позиции
    _connect(client, demo)
    with caplog.at_level("WARNING", logger="satti.kaspi"):
        r = _sync(client, demo)
    assert r.status_code == 200, r.text
    assert r.json()["skipped"] >= 2
    assert len(_numbers(demo["shop_id"])) >= 28
    assert "skipped" in caplog.text and VALID_TOKEN not in caplog.text
    conn = client.get(f"/v1/shops/{demo['shop_id']}/kaspi/connection", headers=demo["headers"]).json()
    assert "Пропущено записей Kaspi" in (conn.get("last_error") or "")


# --- замер на синтетическом магазине ----------------------------------------------------------------------------------

def test_benchmark_500_products_3000_orders_90_days(demo, capsys):
    """Время до первых цифр (14 дней) и до полной загрузки — без сети (мок). Реальное время добавит сеть Kaspi:
    оценка по числу запросов × (0,25 с паузы + ответ Kaspi) — в выводе."""
    m = MockKaspi()
    now = datetime.now(timezone.utc)
    m.generate(3000, now=now, days=89, products=500)
    with DbSession(engine) as db:
        shop = db.get(Shop, demo["shop_id"])
        conn = KaspiConnection(shop_id=shop.id, seller_id="S-1", token_enc=kaspi_service.encrypt_token(VALID_TOKEN),
                               price_key="bench", status="active", connected_at=now)
        db.merge(conn)
        db.commit()
        conn = db.get(KaspiConnection, shop.id)
        client = KaspiClient(VALID_TOKEN, transport=m.transport(), sleep=lambda s: None, min_interval=0)
        conn.backfill_done = True  # сначала только этап 1 — «первые цифры»
        t0 = time.perf_counter()
        kaspi_service.sync(db, conn, client, now)
        t_first = time.perf_counter() - t0
        req_first = m.requests_seen
        conn.backfill_done = False
        conn.backfill_page = 0
        db.commit()
        kaspi_service.sync(db, conn, client, now)
        t_full = time.perf_counter() - t0
        assert db.query(Order).filter(Order.shop_id == shop.id, Order.number.like("KC%")).count() == 3000
    assert m.bad_period_requests == 0
    est = lambda n: n * (0.25 + 0.3)  # noqa: E731 — пауза клиента + типичный ответ Kaspi
    with capsys.disabled():
        print(f"\nзамер К-33 А1: первые цифры — {t_first:.1f} с ({req_first} запросов, с сетью ~ {est(req_first) / 60:.1f} мин);"
              f" полная загрузка — {t_full:.1f} с ({m.requests_seen} запросов, с сетью ~ {est(m.requests_seen) / 60:.1f} мин)")
