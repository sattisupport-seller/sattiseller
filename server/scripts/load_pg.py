"""К-33 Б3: нагрузка на локальном PostgreSQL — N продавцов × M заказов за 90 дней, замер отчётов.

Запуск (отдельная база, боевая не трогается):
  python scripts/load_pg.py --url postgresql+psycopg://postgres:satti@127.0.0.1:55432/satti_load --shops 100 --orders 5000
База пересоздаётся. Данные — синтетические, заливаются через COPY. Замер: обзор за 30 дней, «деньги» (утечки маржи),
склад — у нескольких случайных магазинов, холодный и повторный запрос, плюс пиковая память процесса на расчёт.
"""

from __future__ import annotations

import argparse
import io
import random
import sys
import time
import tracemalloc
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _uid() -> str:
    return uuid.uuid4().hex


def _copy(raw, table: str, cols: list[str], rows) -> int:
    buf = io.StringIO()
    n = 0
    for r in rows:
        buf.write("\t".join("\\N" if v is None else str(v) for v in r) + "\n")
        n += 1
    buf.seek(0)
    with raw.cursor() as cur:
        with cur.copy(f"COPY {table} ({', '.join(cols)}) FROM STDIN") as cp:
            cp.write(buf.read())
    return n


def fill(url: str, shops: int, orders: int, products: int, seed: int = 1) -> dict:
    from sqlalchemy import create_engine, text

    from app.db import Base
    import app.models  # noqa: F401 — все таблицы

    rnd = random.Random(seed)
    base = url.rsplit("/", 1)
    admin = create_engine(base[0] + "/postgres", isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        c.execute(text(f"DROP DATABASE IF EXISTS {base[1]} WITH (FORCE)"))
        c.execute(text(f"CREATE DATABASE {base[1]}"))
    admin.dispose()
    engine = create_engine(url)
    Base.metadata.create_all(engine)
    now = datetime.now(timezone.utc)
    t0 = time.perf_counter()
    statuses = ["completed"] * 7 + ["cancelled", "returned", "in_progress"]
    shop_ids = []
    raw = engine.raw_connection()
    try:
        for s in range(shops):
            sid = _uid()
            shop_ids.append(sid)
            _copy(raw.driver_connection, "shops", ["id", "is_demo", "name", "timezone", "language", "created_at",
                                                   "vat_payer", "presentation_mode", "example_cost_pct"],
                  [(sid, "f", f"Нагрузка {s}", "Asia/Almaty", "ru", now.isoformat(), "f", "f", 60)])
            pids = [_uid() for _ in range(products)]
            _copy(raw.driver_connection, "products", ["id", "shop_id", "sku", "name", "category"],
                  [(pid, sid, f"SKU-{i}", f"Товар {i}", f"Кат {i % 5}") for i, pid in enumerate(pids)])
            _copy(raw.driver_connection, "commission_presets", ["id", "shop_id", "category", "rate_bp", "source",
                                                                "verified", "demo"],
                  [(_uid(), sid, f"Кат {k}", 1250, "manual", "f", "f") for k in range(5)])
            prices = {pid: rnd.randint(1_000, 30_000) * 100 for pid in pids}
            _copy(raw.driver_connection, "product_cost_versions",
                  ["id", "shop_id", "product_id", "purchase_minor", "delivery_to_warehouse_minor", "packaging_minor",
                   "other_minor", "source", "cancelled", "created_at"],
                  [(_uid(), sid, pid, int(prices[pid] * 0.6), 0, 0, 0, "manual", "f", now.isoformat()) for pid in pids])
            order_rows, item_rows = [], []
            for i in range(orders):
                oid = _uid()
                created = now - timedelta(seconds=rnd.randint(0, 90 * 86400))
                st = rnd.choice(statuses)
                done = (created + timedelta(days=1)).isoformat() if st in ("completed", "returned") else None
                order_rows.append((oid, sid, f"L{s:03d}{i:06d}", st, created.isoformat(), done))
                for _ in range(1 + (i % 3 == 0)):
                    pid = rnd.choice(pids)
                    item_rows.append((_uid(), oid, sid, pid, rnd.randint(1, 3), prices[pid],
                                      rnd.choice([0, 0, 58_000, 81_084]), None))
            _copy(raw.driver_connection, "orders", ["id", "shop_id", "number", "status", "created_at", "completed_at"],
                  order_rows)
            _copy(raw.driver_connection, "order_items", ["id", "order_id", "shop_id", "product_id", "qty",
                                                         "unit_price_minor", "buyer_delivery_minor",
                                                         "commission_rate_bp"], item_rows)
            raw.driver_connection.commit()
    finally:
        raw.close()
    with engine.begin() as c:
        c.execute(text("ANALYZE"))
        counts = {t: c.execute(text(f"SELECT COUNT(*) FROM {t}")).scalar() for t in ("orders", "order_items")}  # noqa: S608
    engine.dispose()
    return {"shop_ids": shop_ids, "fill_seconds": round(time.perf_counter() - t0, 1), **counts}


def measure(url: str, shop_ids: list[str], sample: int = 10, seed: int = 2) -> list[dict]:
    import os
    os.environ["DATABASE_URL"] = url
    from sqlalchemy.orm import Session

    from app import reportcache
    from app.db import engine
    from app.insights import money_insights
    from app.models import Shop
    from app.periods import resolve
    from app.reports import base_for, overview
    from app.stock import stock_states

    out = []
    rnd = random.Random(seed)
    now = datetime.now(timezone.utc)
    for sid in rnd.sample(shop_ids, min(sample, len(shop_ids))):
        with Session(engine) as db:
            shop = db.get(Shop, sid)
            reportcache.invalidate(sid)
            tracemalloc.start()
            t = time.perf_counter()
            data, facts = base_for(db, shop)
            overview(data, facts, resolve("30d", shop.timezone, now), now)
            t_over = time.perf_counter() - t
            t = time.perf_counter()
            money_insights(db, data, facts, now)
            t_money = time.perf_counter() - t
            t = time.perf_counter()
            stock_states(db, shop, now)
            t_stock = time.perf_counter() - t
            peak = tracemalloc.get_traced_memory()[1]
            tracemalloc.stop()
            out.append({"shop": sid[:8], "facts": len(facts), "overview_s": round(t_over, 2),
                        "money_s": round(t_money, 2), "stock_s": round(t_stock, 2), "peak_mb": round(peak / 2**20, 1)})
    return out


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--url", required=True)
    p.add_argument("--shops", type=int, default=100)
    p.add_argument("--orders", type=int, default=5000)
    p.add_argument("--products", type=int, default=200)
    p.add_argument("--sample", type=int, default=10)
    a = p.parse_args(argv)
    if "satti_load" not in a.url:
        print("база для нагрузки должна называться satti_load (защита от боевой)")
        return 2
    info = fill(a.url, a.shops, a.orders, a.products)
    print(f"залито: магазинов {a.shops}, заказов {info['orders']}, позиций {info['order_items']} за {info['fill_seconds']} с")
    rows = measure(a.url, info["shop_ids"], a.sample)
    for r in rows:
        print(r)
    worst = max(r["overview_s"] + r["money_s"] + r["stock_s"] for r in rows)
    print(f"худший магазин: {worst:.2f} с на обзор + деньги + склад (холодный, без кэша); "
          f"пик памяти {max(r['peak_mb'] for r in rows)} МБ")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
