"""К-33 Б3: надёжность синхронизации — сбои Kaspi (429, 5xx, таймауты) и «падение базы» посреди загрузки.
Итог после повторов: ровно столько заказов и позиций, сколько у Kaspi; без дублей и без потерь."""

from datetime import datetime, timezone

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session as DbSession

from app import kaspi as kaspi_service
from app.db import engine
from app.kaspi_client import KaspiClient, KaspiUnavailable
from app.models import KaspiConnection, Order, OrderItem, Shop
from tests.kaspi_mock import VALID_TOKEN, MockKaspi

N_ORDERS = 3000


def _setup(demo, chaos: float, seed: int):
    m = MockKaspi(chaos=chaos, chaos_seed=seed)
    now = datetime.now(timezone.utc)
    m.generate(N_ORDERS, now=now, days=89, products=300)
    with DbSession(engine) as db:
        shop = db.get(Shop, demo["shop_id"])
        db.merge(KaspiConnection(shop_id=shop.id, seller_id="S-B3", token_enc=kaspi_service.encrypt_token(VALID_TOKEN),
                                 price_key="b3", status="active", connected_at=now))
        db.commit()
    return m, now


def _sync_until_done(demo, m, now, max_runs=60, before_each=None):
    """Повторяем синхронизацию, как это делает расписание, пока загрузка 90 дней не закончится."""
    runs = failures = 0
    while runs < max_runs:
        runs += 1
        with DbSession(engine) as db:
            conn = db.get(KaspiConnection, demo["shop_id"])
            client = KaspiClient(VALID_TOKEN, transport=m.transport(), sleep=lambda s: None, min_interval=0)
            try:
                if before_each:
                    before_each(runs)
                kaspi_service.sync(db, conn, client, now)
            except (KaspiUnavailable, OperationalError):
                failures += 1
                db.rollback()
                continue
            if conn.backfill_done:
                return runs, failures
    raise AssertionError(f"загрузка не закончилась за {max_runs} запусков")


def _check_exact(demo, m):
    with DbSession(engine) as db:
        numbers = db.scalars(select(Order.number).where(Order.shop_id == demo["shop_id"],
                                                        Order.number.like("KC%"))).all()
        items_qty = db.scalar(select(func.coalesce(func.sum(OrderItem.qty), 0)).join(Order, Order.id == OrderItem.order_id)
                              .where(Order.shop_id == demo["shop_id"], Order.number.like("KC%")))
    assert len(numbers) == N_ORDERS, f"заказов {len(numbers)} из {N_ORDERS}"
    assert len(set(numbers)) == len(numbers), "есть дубли заказов"
    expected_qty = sum(row["qty"] for rows in m.entries.values() for row in rows)
    assert items_qty == expected_qty, f"штук в позициях {items_qty}, у Kaspi {expected_qty}"


@pytest.mark.parametrize("seed", [7, 21])
def test_sync_survives_20_percent_kaspi_failures(demo, seed):
    m, now = _setup(demo, chaos=0.20, seed=seed)
    runs, failures = _sync_until_done(demo, m, now)
    _check_exact(demo, m)
    assert sum(m.chaos_seen.values()) > 50 and set(m.chaos_seen) == {"429", "500", "503", "timeout"}
    print(f"\nК-33 Б3 хаос seed={seed}: запусков {runs}, неудачных {failures}, сбоев Kaspi {m.chaos_seen}")


def test_sync_survives_database_going_down_mid_load(demo, monkeypatch):
    """«Падение базы»: на некоторых страницах сохранение заказов обрывается ошибкой соединения (как при
    перезапуске PostgreSQL). Следующий запуск продолжает; заказы не дублируются и не теряются."""
    m, now = _setup(demo, chaos=0.0, seed=1)
    real_apply = kaspi_service._apply_page
    calls = {"n": 0}

    def flaky_apply(db, *args, **kwargs):
        calls["n"] += 1
        result = real_apply(db, *args, **kwargs)
        if calls["n"] in (2, 5, 9):  # страница записана в сессию, но до фиксации «база упала»
            raise OperationalError("COMMIT", {}, Exception("server closed the connection unexpectedly"))
        return result

    monkeypatch.setattr(kaspi_service, "_apply_page", flaky_apply)
    runs, failures = _sync_until_done(demo, m, now)
    assert failures >= 3
    _check_exact(demo, m)


def test_partial_cancel_of_open_order_is_caught_by_regular_sync(client, demo):
    """Заказ ещё не выдан — частичная отмена видна в обычной синхронизации сразу (позиции перечитываются)."""
    from tests.test_kaspi import _connect

    m, now = _setup(demo, chaos=0.0, seed=1)
    m.orders.clear()
    m.entries.clear()
    m.generate(6, now=now, days=3, state_cycle=["ACCEPTED_BY_MERCHANT"], products=2)
    with DbSession(engine) as db:
        conn = db.get(KaspiConnection, demo["shop_id"])
        client_k = KaspiClient(VALID_TOKEN, transport=m.transport(), sleep=lambda s: None, min_interval=0)
        kaspi_service.sync(db, conn, client_k, now)
    code = next(c for c, rows in m.entries.items() if rows[0]["qty"] >= 2)
    m.partial_cancel(code, 0, 1)
    with DbSession(engine) as db:
        conn = db.get(KaspiConnection, demo["shop_id"])
        client_k = KaspiClient(VALID_TOKEN, transport=m.transport(), sleep=lambda s: None, min_interval=0)
        res = kaspi_service.sync(db, conn, client_k, now)
        order = db.scalar(select(Order).where(Order.shop_id == demo["shop_id"], Order.number == code))
        qty = db.scalar(select(func.sum(OrderItem.qty)).where(OrderItem.order_id == order.id))
    assert res["items_changed"] >= 1 and qty == sum(r["qty"] for r in m.entries[code])
    assert _connect  # импорт фикстуры-помощника не нужен; оставлен для единообразия
