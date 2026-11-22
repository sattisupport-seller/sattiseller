"""К-17.3 (аудит): первая загрузка большого магазина — сколько запросов к Kaspi на заказы (мок)."""

from datetime import datetime, timezone

import pytest
from sqlalchemy.orm import Session as DbSession

from app import kaspi as kaspi_service
from app.db import engine
from app.kaspi_client import KaspiClient
from app.models import KaspiConnection, Shop
from tests.kaspi_mock import MockKaspi, VALID_TOKEN


@pytest.mark.parametrize("orders", [1000])
def test_first_load_request_count_per_order(demo, monkeypatch, orders):
    m = MockKaspi()
    now = datetime.now(timezone.utc)
    m.generate(orders, now=now, days=80, products=max(50, orders // 10))
    with DbSession(engine) as db:
        shop = db.get(Shop, demo["shop_id"])
        conn = db.get(KaspiConnection, demo["shop_id"])
        if conn is None:
            conn = KaspiConnection(shop_id=shop.id, seller_id="S-1", token_enc=kaspi_service.encrypt_token(VALID_TOKEN),
                                   price_key="k", status="active", connected_at=now)
            db.add(conn)
            db.commit()
        client = KaspiClient(VALID_TOKEN, transport=m.transport(), sleep=lambda s: None, min_interval=0)
        conn.cursor_ms = None
        db.commit()
        result = kaspi_service.sync(db, conn, client, now)
        assert result["added"] == orders
    per_order = m.requests_seen / orders
    print(f"\nпервая загрузка: {orders} заказов, запросов {m.requests_seen}, на заказ {per_order:.2f}")
    assert per_order < 4  # список + позиции + связи товара; без повторов по товарам
