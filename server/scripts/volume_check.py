"""Замер на объёме (MASTER_PLAN 2.5, сюрприз 13 из К-17): 10 000 товаров в прайсе и 5 000+ заказов Kaspi на моке.

Что меряем: время первой загрузки (этап 7 дней + догрузка 90 дней до конца), время отчётов (обзор, разбивка прибыли,
список товаров, склад, «не настроенные» товары), пиковая память Python (tracemalloc) и память процесса.
База — отдельная SQLite во временной папке; реальный Kaspi не вызывается.

Запуск из папки server:  .venv\\Scripts\\python scripts/volume_check.py --products 10000 --orders 5000
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
import time
import tracemalloc
import uuid
from datetime import datetime, timezone
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="satti-volume-"))
os.environ["DATABASE_URL"] = f"sqlite:///{(TMP / 'volume.db').as_posix()}"
os.environ.setdefault("SATTI_DATA_DIR", str(TMP))
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _rss_mb() -> float | None:
    try:
        import psutil  # type: ignore

        return psutil.Process().memory_info().rss / 1024 ** 2
    except Exception:  # noqa: BLE001 — psutil не обязателен
        return None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--products", type=int, default=10_000)
    parser.add_argument("--orders", type=int, default=5_000)
    args = parser.parse_args()

    from app import kaspi as kaspi_service
    from app.db import Base, engine
    from app.kaspi_client import KaspiClient
    from app.models import KaspiConnection, Order, OrderItem, Product, Shop, User
    from app.reports import missing_costs
    from app.stock import stock_states
    from sqlalchemy import func, select
    from sqlalchemy.orm import Session as DbSession
    from tests.kaspi_mock import MockKaspi

    import app.reportcache  # noqa: F401
    from app import api as api_module

    Base.metadata.create_all(engine)
    now = datetime.now(timezone.utc)

    class IndexedMock(MockKaspi):
        """Тот же мок, но поиск позиции по id — по словарю (в тестовом моке он линейный)."""

        def _entry_by_id(self, entry_id):  # noqa: D401
            if not hasattr(self, "_idx"):
                self._idx = {r["id"]: r for rows in self.entries.values() for r in rows}
            return self._idx[entry_id]

    mock = IndexedMock()
    mock.generate(args.orders, now=now, days=90, products=args.products)

    with DbSession(engine) as db:
        user = User(email=f"volume-{uuid.uuid4().hex[:6]}@example.invalid")
        db.add(user)
        db.flush()
        shop = Shop(owner_user_id=user.id, name="Объём", timezone="Asia/Almaty", language="ru")
        db.add(shop)
        db.commit()
        shop_id = shop.id
        # прайс продавца на 10 000 товаров (stockCount — подсказка остатка, К-24)
        offers = "".join(
            f'<offer sku="K{i}"><model>Товар K{i}</model><availabilities><availability available="yes" '
            f'storeId="PP1" stockCount="{i % 40}"/></availabilities><price>{1000 + 10 * i}</price></offer>'
            for i in range(args.products))
        xml = f'<kaspi_catalog xmlns="kaspiShopping"><company>Объём</company><offers>{offers}</offers></kaspi_catalog>'
        t0 = time.perf_counter()
        kaspi_service.import_catalog(db, shop_id, xml.encode("utf-8"), now)
        t_catalog = time.perf_counter() - t0

    tracemalloc.start()
    client = KaspiClient(mock.token, transport=mock.transport(), sleep=lambda s: None, min_interval=0)
    with DbSession(engine) as db:
        conn = KaspiConnection(shop_id=shop_id, seller_id="VOLUME", token_enc=kaspi_service.encrypt_token(mock.token),
                               price_key=uuid.uuid4().hex)
        db.add(conn)
        db.commit()
        t0 = time.perf_counter()
        passes = 0
        while True:
            conn = db.get(KaspiConnection, shop_id)
            kaspi_service.sync(db, conn, client, now)
            passes += 1
            db.refresh(conn)
            if conn.backfill_done or passes > 500:
                break
        t_load = time.perf_counter() - t0
        orders = db.scalar(select(func.count()).select_from(Order).where(Order.shop_id == shop_id))
        items = db.scalar(select(func.count()).select_from(OrderItem).where(OrderItem.shop_id == shop_id))
        products = db.scalar(select(func.count()).select_from(Product).where(Product.shop_id == shop_id))
    _, peak_load = tracemalloc.get_traced_memory()
    tracemalloc.reset_peak()

    timings: dict[str, float] = {}
    with DbSession(engine) as db:
        shop = db.get(Shop, shop_id)
        for name, fn in (
            ("base_for (загрузка данных магазина)", lambda: api_module.base_for(db, shop)),
            ("обзор 30 дней", lambda: api_module.overview(*api_module.base_for(db, shop),
                                                          api_module._period("30d", shop), now)),
            ("не настроенные товары", lambda: api_module._unconfigured(db, shop)),
            ("товары без себестоимости", lambda: missing_costs(api_module.base_for(db, shop)[0])),
            ("склад", lambda: stock_states(db, shop, now)),
            ("прайс-лист XML для Kaspi", lambda: kaspi_service.price_list_xml(db, shop, db.get(KaspiConnection, shop_id))),
        ):
            t0 = time.perf_counter()
            fn()
            timings[name] = time.perf_counter() - t0
    _, peak_reports = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    print(f"Объём: прайс {args.products} товаров, заказов Kaspi {args.orders}")
    print(f"В базе: заказов {orders}, позиций {items}, товаров {products}")
    print(f"Импорт прайса: {t_catalog:.1f} с")
    print(f"Первая загрузка (7 дней + догрузка 90 дней, проходов {passes}): {t_load:.1f} с; пик памяти Python {peak_load / 1024 ** 2:.0f} МБ")
    for name, sec in timings.items():
        print(f"  {name}: {sec:.2f} с")
    print(f"Пик памяти Python на отчётах: {peak_reports / 1024 ** 2:.0f} МБ")
    rss = _rss_mb()
    if rss is not None:
        print(f"Память процесса: {rss:.0f} МБ")
    print(f"База: {TMP / 'volume.db'} ({(TMP / 'volume.db').stat().st_size / 1024 ** 2:.0f} МБ)")


if __name__ == "__main__":
    main()
