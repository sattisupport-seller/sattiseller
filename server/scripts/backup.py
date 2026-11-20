"""Бэкапы Satti (ADR-0005: ежедневно, хранить 14 дней, копия во второе S3-совместимое хранилище).

Команды (запускаются из папки server):
  python scripts/backup.py genkey                 — создать ключ шифрования бэкапов (показать один раз, сохранить в менеджер паролей)
  python scripts/backup.py create                 — дамп базы + secret_key -> зашифрованный файл; выгрузка в S3; очистка старых копий
  python scripts/backup.py restore FILE --target-url URL [--yes]
                                                  — расшифровать и восстановить в ДРУГУЮ базу (боевая защищена флагом --yes)
  python scripts/backup.py prune                  — удалить локальные копии старше SATTI_BACKUP_KEEP_DAYS (по умолчанию 14)

Переменные окружения: DATABASE_URL, SATTI_BACKUP_KEY (обязателен), SATTI_BACKUP_DIR (по умолчанию ./backups),
SATTI_BACKUP_KEEP_DAYS, SATTI_PG_BIN (папка с pg_dump и pg_restore, если они не в PATH),
SATTI_S3_BUCKET, SATTI_S3_ENDPOINT, SATTI_S3_ACCESS_KEY, SATTI_S3_SECRET_KEY, SATTI_S3_REGION (необязательно).

Секреты (ключ бэкапов, ключи S3) — только в переменных окружения, в файлах и логах не выводятся.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

FORMAT_VERSION = 1


def _keep_days() -> int:
    return int(os.environ.get("SATTI_BACKUP_KEEP_DAYS", "14"))


def _backup_dir() -> Path:
    return Path(os.environ.get("SATTI_BACKUP_DIR", ROOT / "backups"))


def _fernet() -> Fernet:
    key = os.environ.get("SATTI_BACKUP_KEY", "")
    if not key:
        raise SystemExit("SATTI_BACKUP_KEY не задан. Бэкап без шифрования не создаётся: python scripts/backup.py genkey")
    return Fernet(key.encode("ascii"))


def _db_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        raise SystemExit("DATABASE_URL не задан")
    return url


def _pg_tool(name: str) -> str:
    bin_dir = os.environ.get("SATTI_PG_BIN")
    if bin_dir:
        candidate = Path(bin_dir) / (name + (".exe" if os.name == "nt" else ""))
        if candidate.exists():
            return str(candidate)
    found = shutil.which(name)
    if not found:
        raise SystemExit(f"{name} не найден: установите клиент PostgreSQL или задайте SATTI_PG_BIN")
    return found


def _libpq_url(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://").replace("postgresql+psycopg2://", "postgresql://")


def dump_database(tmp: Path) -> str:
    """Дамп базы во временный файл. Возвращает тип базы."""
    url = _db_url()
    if url.startswith("sqlite"):
        src = url.split(":///", 1)[1]
        src_conn = sqlite3.connect(src)
        dst_conn = sqlite3.connect(str(tmp / "db.sqlite"))
        with dst_conn:
            src_conn.backup(dst_conn)  # согласованная копия, даже если база открыта сервером
        dst_conn.close()
        src_conn.close()
        return "sqlite"
    subprocess.run([_pg_tool("pg_dump"), "--format=custom", "--no-owner", "--no-privileges",
                    f"--file={tmp / 'db.dump'}", _libpq_url(url)], check=True)
    return "postgresql"


def build_archive(db_kind: str, tmp: Path) -> bytes:
    """Упаковка: дамп, secret_key (если есть) и манифест с контрольными суммами."""
    from app.config import DATA_DIR

    buf = io.BytesIO()
    members: dict[str, str] = {}
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for path in sorted(tmp.iterdir()):
            tar.add(path, arcname=path.name)
            members[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
        secret = DATA_DIR / "secret_key"
        if secret.exists():  # без него восстановленные сессии и отметки пробного периода не сходятся с хешами
            data = secret.read_bytes()
            info = tarfile.TarInfo("secret_key")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
            members["secret_key"] = hashlib.sha256(data).hexdigest()
        manifest = json.dumps({"format": FORMAT_VERSION, "db": db_kind,
                               "created": datetime.now(timezone.utc).isoformat(), "sha256": members},
                              ensure_ascii=False).encode("utf-8")
        info = tarfile.TarInfo("manifest.json")
        info.size = len(manifest)
        tar.addfile(info, io.BytesIO(manifest))
    return buf.getvalue()


def create(out_dir: Path | None = None) -> Path:
    fernet = _fernet()  # проверка ключа до дампа
    out = out_dir or _backup_dir()
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        kind = dump_database(tmp)
        archive = build_archive(kind, tmp)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")  # микросекунды: две копии в одну секунду не затирают друг друга
    target = out / f"satti-{stamp}.bak"
    target.write_bytes(fernet.encrypt(archive))
    _upload_s3(target)
    prune(out)
    return target


def restore(file: Path, target_url: str, assume_yes: bool) -> None:
    fernet = _fernet()
    try:
        archive = fernet.decrypt(file.read_bytes())
    except InvalidToken as exc:
        raise SystemExit("Не удалось расшифровать копию: неверный SATTI_BACKUP_KEY или файл повреждён") from exc
    if target_url == os.environ.get("DATABASE_URL") and not assume_yes:
        raise SystemExit("Цель совпадает с боевой базой DATABASE_URL. Восстановление отменено. Добавьте --yes, если это намеренно.")
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as tar:
            tar.extractall(tmp, filter="data")
        manifest = json.loads((tmp / "manifest.json").read_text(encoding="utf-8"))
        for name, digest in manifest["sha256"].items():
            if hashlib.sha256((tmp / name).read_bytes()).hexdigest() != digest:
                raise SystemExit(f"Контрольная сумма не совпадает: {name}")
        if manifest["db"] == "sqlite":
            dst = target_url.split(":///", 1)[1]
            Path(dst).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(tmp / "db.sqlite", dst)
        else:
            subprocess.run([_pg_tool("pg_restore"), "--clean", "--if-exists", "--no-owner",
                            f"--dbname={_libpq_url(target_url)}", str(tmp / "db.dump")], check=True)
        if (tmp / "secret_key").exists():
            from app.config import DATA_DIR

            dst_key = DATA_DIR / "secret_key"
            if not dst_key.exists():  # не перезаписываем существующий ключ
                DATA_DIR.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(tmp / "secret_key", dst_key)
    print(f"восстановлено в {target_url.split('@')[-1]}; копия от {manifest['created']}")


def prune(out: Path) -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(days=_keep_days())
    removed = 0
    for f in out.glob("satti-*.bak"):
        if datetime.fromtimestamp(f.stat().st_mtime, timezone.utc) < cutoff:
            f.unlink()
            removed += 1
    return removed


def _s3_client():
    bucket = os.environ.get("SATTI_S3_BUCKET")
    if not bucket:
        return None, None
    import boto3  # локальный импорт: нужен только при настроенном хранилище

    client = boto3.client("s3", endpoint_url=os.environ.get("SATTI_S3_ENDPOINT") or None,
                          aws_access_key_id=os.environ.get("SATTI_S3_ACCESS_KEY"),
                          aws_secret_access_key=os.environ.get("SATTI_S3_SECRET_KEY"),
                          region_name=os.environ.get("SATTI_S3_REGION") or None)
    return client, bucket


def _upload_s3(path: Path) -> None:
    client, bucket = _s3_client()
    if client is None:
        return
    client.upload_file(str(path), bucket, f"satti/{path.name}")
    cutoff = datetime.now(timezone.utc) - timedelta(days=_keep_days())
    for obj in client.list_objects_v2(Bucket=bucket, Prefix="satti/").get("Contents", []):
        if obj["LastModified"] < cutoff:
            client.delete_object(Bucket=bucket, Key=obj["Key"])


def genkey() -> str:
    return Fernet.generate_key().decode("ascii")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Бэкапы Satti")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("genkey")
    sub.add_parser("create")
    sub.add_parser("prune")
    r = sub.add_parser("restore")
    r.add_argument("file", type=Path)
    r.add_argument("--target-url", required=True)
    r.add_argument("--yes", action="store_true")
    args = parser.parse_args(argv)
    if args.cmd == "genkey":
        print(genkey())
    elif args.cmd == "create":
        print(create())
    elif args.cmd == "prune":
        print(f"удалено: {prune(_backup_dir())}")
    elif args.cmd == "restore":
        restore(args.file, args.target_url, args.yes)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
