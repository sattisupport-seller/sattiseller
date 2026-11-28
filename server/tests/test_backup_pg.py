"""К-33 Б3: копия на PostgreSQL — pg_dump → шифрование → восстановление в другую базу → сверка строк и содержимого.

Нужны PostgreSQL (SATTI_TEST_DATABASE_URL) и pg_dump/pg_restore той же версии (SATTI_PG_BIN). Без них — пропуск:
в CI старый клиент PostgreSQL может отказаться работать с сервером 16. Локально запускается из release_check.
"""

import importlib.util
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

PG_URL = os.environ.get("SATTI_TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(not (PG_URL.startswith("postgresql") and os.environ.get("SATTI_PG_BIN")),
                                reason="нужны SATTI_TEST_DATABASE_URL (PostgreSQL) и SATTI_PG_BIN")

_spec = importlib.util.spec_from_file_location("satti_backup_pg", Path(__file__).resolve().parent.parent / "scripts" / "backup.py")
backup = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(backup)


def _db(name: str) -> str:
    return PG_URL.rsplit("/", 1)[0] + "/" + name


@pytest.fixture
def pg_pair(tmp_path, monkeypatch):
    admin = create_engine(_db("postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        for n in ("satti_b3_src", "satti_b3_dst"):
            c.execute(text(f"DROP DATABASE IF EXISTS {n} WITH (FORCE)"))
            c.execute(text(f"CREATE DATABASE {n}"))
    monkeypatch.setenv("DATABASE_URL", _db("satti_b3_src"))
    monkeypatch.setenv("SATTI_BACKUP_KEY", Fernet.generate_key().decode("ascii"))
    monkeypatch.setenv("SATTI_BACKUP_DIR", str(tmp_path / "backups"))
    monkeypatch.delenv("SATTI_S3_BUCKET", raising=False)
    yield _db("satti_b3_src"), _db("satti_b3_dst")
    with admin.connect() as c:
        for n in ("satti_b3_src", "satti_b3_dst"):
            c.execute(text(f"DROP DATABASE IF EXISTS {n} WITH (FORCE)"))
    admin.dispose()


def _fill(url: str, n_orders: int = 300) -> None:
    from app.db import Base
    from app.models import Order, OrderItem, Product, Shop

    engine = create_engine(url)
    Base.metadata.create_all(engine)
    now = datetime(2026, 11, 28, 6, 30, tzinfo=timezone.utc)
    with Session(engine) as s:
        shop = Shop(name="Магазин «Ёлка» № 1", timezone="Asia/Almaty")
        s.add(shop)
        s.flush()
        products = [Product(shop_id=shop.id, sku=f"SKU-{i:03d}", name=f"Товар {i} — «кавычки», ёж", category="Посуда")
                    for i in range(20)]
        s.add_all(products)
        s.flush()
        for i in range(n_orders):
            o = Order(shop_id=shop.id, number=f"KC{i:08d}", status=("completed", "cancelled", "returned")[i % 3],
                      created_at=now - timedelta(hours=i), completed_at=now - timedelta(hours=i - 1) if i % 3 else None)
            s.add(o)
            s.flush()
            s.add(OrderItem(order_id=o.id, shop_id=shop.id, product_id=products[i % 20].id, qty=1 + i % 4,
                            unit_price_minor=9_999_999_99 + i, buyer_delivery_minor=58_000 if i % 2 else None,
                            commission_rate_bp=1250))
        s.commit()
    engine.dispose()


def test_pg_roundtrip_same_counts_and_content(pg_pair, tmp_path):
    src, dst = pg_pair
    _fill(src)
    copy = backup.create(tmp_path / "out")
    assert copy.read_bytes()[:5] != b"PGDMP"  # зашифровано
    manifest_counts = backup.table_counts(src)
    manifest_sums = backup.table_checksums(src)
    assert manifest_counts["orders"] == 300 and manifest_counts["order_items"] == 300

    backup.restore(copy, dst, assume_yes=False)
    assert backup.table_counts(dst) == manifest_counts
    assert backup.table_checksums(dst) == manifest_sums


def test_pg_checksum_catches_changed_value_with_same_row_count(pg_pair, tmp_path):
    src, dst = pg_pair
    _fill(src, n_orders=50)
    copy = backup.create(tmp_path / "out")
    backup.restore(copy, dst, assume_yes=False)
    before = backup.table_checksums(dst)
    engine = create_engine(dst)
    with engine.begin() as c:  # «тихая» порча: число строк то же, сумма другая
        c.execute(text("UPDATE order_items SET unit_price_minor = unit_price_minor + 1 "
                       "WHERE id = (SELECT min(id) FROM order_items)"))
    engine.dispose()
    assert backup.table_counts(dst)["order_items"] == 50
    after = backup.table_checksums(dst)
    assert after["order_items"] != before["order_items"]
    assert {k for k in after if after[k] != before[k]} == {"order_items"}


def test_pg_verify_restores_latest_and_checks_content(pg_pair, tmp_path):
    src, dst = pg_pair
    _fill(src, n_orders=40)
    backup.create()  # в SATTI_BACKUP_DIR — как ночная копия
    problems = backup.verify(dst)
    assert problems == [], problems
