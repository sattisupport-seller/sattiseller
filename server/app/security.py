"""Токены, коды входа и их хеши. Секрет сервера создаётся при первом запуске (data/secret_key)."""

import hashlib
import hmac
import secrets

from .config import DATA_DIR

_SECRET_FILE = DATA_DIR / "secret_key"
_secret_cache: bytes | None = None


def _secret() -> bytes:
    global _secret_cache
    if _secret_cache is None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        if not _SECRET_FILE.exists():
            _SECRET_FILE.write_text(secrets.token_hex(32), encoding="utf-8")
        _secret_cache = _SECRET_FILE.read_text(encoding="utf-8").strip().encode()
    return _secret_cache


def new_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hmac.new(_secret(), token.encode(), hashlib.sha256).hexdigest()


def new_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def hash_code(email: str, code: str) -> str:
    return hmac.new(_secret(), f"{email.lower()}:{code}".encode(), hashlib.sha256).hexdigest()


def hash_device_id(device_id: str) -> str:
    return hmac.new(_secret(), f"device:{device_id}".encode(), hashlib.sha256).hexdigest()
