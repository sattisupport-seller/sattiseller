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


def test_alembic_downgrade_needs_explicit_flag(tmp_path):
    """QA-12: откат без SATTI_ALLOW_DOWNGRADE=1 отказывает; с флагом выполняется."""
    import subprocess
    import sys

    root = Path(__file__).resolve().parent.parent
    env = {**os.environ, "DATABASE_URL": f"sqlite:///{(tmp_path / 'mig.db').as_posix()}",
           "SATTI_DATA_DIR": str(tmp_path / "data")}
    env.pop("SATTI_ALLOW_DOWNGRADE", None)
    up = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, env=env, capture_output=True)
    assert up.returncode == 0, up.stderr[-400:]
    down = subprocess.run([sys.executable, "-m", "alembic", "downgrade", "base"], cwd=root, env=env, capture_output=True)
    assert down.returncode != 0
    assert b"SATTI_ALLOW_DOWNGRADE" in (down.stdout + down.stderr)
    env["SATTI_ALLOW_DOWNGRADE"] = "1"
    down2 = subprocess.run([sys.executable, "-m", "alembic", "downgrade", "base"], cwd=root, env=env, capture_output=True)
    assert down2.returncode == 0, down2.stderr[-400:]


class FakeS3:
    """S3-совместимое хранилище другой компании (мок): list_objects_v2, upload_file, download_file, delete_object."""

    def __init__(self):
        self.objects: dict[str, tuple[bytes, object]] = {}

    def upload_file(self, path, bucket, key):
        from datetime import datetime, timezone
        self.objects[key] = (Path(path).read_bytes(), datetime.now(timezone.utc))

    def list_objects_v2(self, Bucket, Prefix):  # noqa: N803 — имена как у boto3
        return {"Contents": [{"Key": k, "LastModified": t} for k, (_, t) in self.objects.items() if k.startswith(Prefix)]}

    def download_file(self, bucket, key, path):
        Path(path).write_bytes(self.objects[key][0])

    def delete_object(self, Bucket, Key):  # noqa: N803
        self.objects.pop(Key, None)


@pytest.fixture
def s3(monkeypatch):
    fake = FakeS3()
    monkeypatch.setattr(backup, "_s3_client", lambda: (fake, "satti-backups"))
    return fake


def test_restore_latest_from_s3_on_clean_server(sqlite_db, tmp_path, s3, monkeypatch):
    """К-21 ч.2 п.8: хостинг пропал — на новом сервере одной командой последняя копия из S3 другой компании."""
    backup.create(tmp_path / "out")
    conn = sqlite3.connect(sqlite_db)
    conn.execute("insert into shops values ('c3', 'Магазин Три')")
    conn.commit()
    conn.close()
    time.sleep(0.01)
    backup.create(tmp_path / "out")  # вторая, более новая копия
    assert len(s3.objects) == 2
    # «чистый сервер»: локальных копий нет, только хранилище
    monkeypatch.setenv("SATTI_BACKUP_DIR", str(tmp_path / "empty"))
    target = tmp_path / "new-server.db"
    backup.restore_latest(f"sqlite:///{target.as_posix()}", assume_yes=False)
    rows = sqlite3.connect(target).execute("select id from shops order by id").fetchall()
    assert rows == [("a1",), ("b2",), ("c3",)]  # из последней копии


def test_verify_passes_and_checks_counts(sqlite_db, tmp_path, s3):
    """К-21 ч.2 п.9: ежедневная проверка — восстановление во временную базу и сверка числа строк."""
    backup.create(tmp_path / "out")
    scratch = tmp_path / "scratch.db"
    assert backup.verify(f"sqlite:///{scratch.as_posix()}") == []


def test_verify_reports_old_or_broken_copy_to_owner(sqlite_db, tmp_path, s3, monkeypatch):
    from datetime import datetime, timedelta, timezone

    sent = []
    import app.mailer as mailer
    monkeypatch.setattr(mailer, "send_owner_alert", lambda subject, text: sent.append((subject, text)) or True)
    backup.create(tmp_path / "out")
    scratch = f"sqlite:///{(tmp_path / 'scratch.db').as_posix()}"
    later = datetime.now(timezone.utc) + timedelta(hours=30)
    problems = backup.verify(scratch, now=later)
    assert any("старше 26 часов" in p for p in problems) and sent
    key = next(iter(s3.objects))
    data, t = s3.objects[key]
    s3.objects[key] = (data[:-10] + b"0" * 10, t)  # повреждённая копия
    problems = backup.verify(scratch)
    assert any("восстановление не удалось" in p for p in problems)


def test_verify_refuses_production_as_scratch(sqlite_db, s3):
    assert backup.verify(os.environ["DATABASE_URL"]) == ["временная база совпадает с боевой — проверка не запущена"]
