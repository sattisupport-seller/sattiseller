"""QA-11: бэкапы — шифрование, роундтрип, защита боевой базы, очистка по сроку. Проверено на SQLite; PostgreSQL — учения вручную."""

import importlib.util
import os
import sqlite3
import time
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

_spec = importlib.util.spec_from_file_location("satti_backup", Path(__file__).resolve().parent.parent / "scripts" / "backup.py")
backup = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(backup)


@pytest.fixture
def sqlite_db(tmp_path, monkeypatch):
    db = tmp_path / "prod.db"
    conn = sqlite3.connect(db)
    conn.execute("create table shops (id text primary key, name text)")
    conn.executemany("insert into shops values (?, ?)", [("a1", "Магазин Один"), ("b2", "Магазин Два")])
    conn.commit()
    conn.close()
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db.as_posix()}")
    monkeypatch.setenv("SATTI_BACKUP_KEY", Fernet.generate_key().decode("ascii"))
    monkeypatch.setenv("SATTI_BACKUP_DIR", str(tmp_path / "backups"))
    monkeypatch.delenv("SATTI_S3_BUCKET", raising=False)
    return db


def test_backup_refuses_without_key(sqlite_db, monkeypatch, tmp_path):
    monkeypatch.delenv("SATTI_BACKUP_KEY")
    with pytest.raises(SystemExit):
        backup.create(tmp_path / "out")


def test_roundtrip_restores_the_same_rows(sqlite_db, tmp_path, monkeypatch):
    copy = backup.create(tmp_path / "out")
    assert copy.read_bytes()[:4] != b"\x1f\x8b\x08\x00"  # файл зашифрован, не gzip
    target = tmp_path / "restored.db"
    backup.restore(copy, f"sqlite:///{target.as_posix()}", assume_yes=False)
    rows = sqlite3.connect(target).execute("select id, name from shops order by id").fetchall()
    assert rows == [("a1", "Магазин Один"), ("b2", "Магазин Два")]


def test_restore_into_production_needs_explicit_yes(sqlite_db, tmp_path):
    copy = backup.create(tmp_path / "out")
    with pytest.raises(SystemExit):
        backup.restore(copy, os.environ["DATABASE_URL"], assume_yes=False)


def test_tampered_backup_is_rejected(sqlite_db, tmp_path):
    copy = backup.create(tmp_path / "out")
    data = bytearray(copy.read_bytes())
    data[len(data) // 2] ^= 0xFF
    copy.write_bytes(bytes(data))
    with pytest.raises(SystemExit):
        backup.restore(copy, f"sqlite:///{(tmp_path / 'x.db').as_posix()}", assume_yes=False)


def test_prune_removes_copies_older_than_retention(sqlite_db, tmp_path):
    out = tmp_path / "out"
    old = backup.create(out)
    new = backup.create(out)
    thirty_days_ago = time.time() - 30 * 86400
    os.utime(old, (thirty_days_ago, thirty_days_ago))
    assert backup.prune(out) == 1
    assert not old.exists() and new.exists()
