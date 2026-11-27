"""Пробный период — один на телефон навсегда (решение владельца 23.11.2026, К-21).

iPhone — Apple DeviceCheck: два бита на устройство хранятся у Apple и переживают полный сброс телефона.
Android — Play Integrity, device recall (бета): значения хранятся у Google и переживают переустановку и сброс.
Отметка «пробный период был» — бит bit0 (Apple) или bitFirst (Google); ставится, когда пробный период начался.

Идентификаторы устройства сервер не получает и не хранит: приложение присылает одноразовый токен, сервер
спрашивает Apple или Google. Если проверка недоступна (нет ключей, эмулятор, сбой) — пробный период не даётся,
причина пишется в журнал (без токена).

Режимы (SATTI_DEVICE_CHECK_MODE): off — проверка не настроена; fake — тесты и разработка, токен считается
меткой телефона (хеш в billing_marks); store — настоящие API Apple и Google (ключи — после аккаунтов).
Формат Play Integrity device recall взят из документации беты — сверить при включении (docs/OWNER_TODO.md).
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass

import jwt
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from . import store_billing
from .config import settings

log = logging.getLogger("satti.device")

APPLE_DEVICECHECK = {"Production": "https://api.devicecheck.apple.com/v1",
                     "Sandbox": "https://api.development.devicecheck.apple.com/v1"}
PLAY_INTEGRITY = "https://playintegrity.googleapis.com/v1"
PLAY_INTEGRITY_SCOPE = "https://www.googleapis.com/auth/playintegrity"


@dataclass
class DeviceVerdict:
    available: bool
    trial_used: bool
    reason: str = ""


def _unavailable(reason: str) -> DeviceVerdict:
    log.info("device check unavailable: %s", reason)
    return DeviceVerdict(available=False, trial_used=False, reason=reason)


def check(db: DbSession, platform: str | None, token: str | None) -> DeviceVerdict:
    if not token or platform not in ("ios", "android"):
        return _unavailable("нет токена проверки телефона (эмулятор, Expo Go или старая версия приложения)")
    mode = settings.device_check_mode
    if mode == "fake":
        from .billing import BillingMark, _hash

        used = db.scalar(select(BillingMark.id).where(BillingMark.kind == "device",
                                                      BillingMark.key_hash == _hash("device", token)))
        return DeviceVerdict(available=True, trial_used=used is not None)
    if mode != "store":
        return _unavailable("проверка телефона не настроена (SATTI_DEVICE_CHECK_MODE)")
    try:
        return _apple_query(token) if platform == "ios" else _google_query(token)
    except store_billing.StoreNotConfigured as exc:
        return _unavailable(f"нет ключа: {exc}")
    except Exception as exc:  # noqa: BLE001 — любой сбой внешней проверки = пробный период не даём
        return _unavailable(f"сбой проверки: {type(exc).__name__}")


def mark_trial(db: DbSession, platform: str | None, token: str | None) -> bool:
    """Ставит отметку «пробный период был». False — не удалось (причина в журнале)."""
    if not token or platform not in ("ios", "android"):
        return False
    mode = settings.device_check_mode
    if mode == "fake":
        from .billing import BillingMark, _hash

        db.add(BillingMark(kind="device", key_hash=_hash("device", token)))  # гонка — уникальное ограничение
        return True
    if mode != "store":
        return False
    try:
        if platform == "ios":
            _apple_update(token)
        else:
            _google_write(token)
        return True
    except Exception as exc:  # noqa: BLE001
        log.warning("device mark failed: %s", type(exc).__name__)
        return False


# ---------- Apple DeviceCheck ----------

def _apple_jwt() -> str:
    team = settings.apple_team_id
    if not (team and settings.apple_devicecheck_key_id):
        raise store_billing.StoreNotConfigured("SATTI_APPLE_TEAM_ID / SATTI_APPLE_DEVICECHECK_KEY_ID")
    key = store_billing._read_secret(settings.apple_devicecheck_key_path)
    return jwt.encode({"iss": team, "iat": int(time.time())}, key, algorithm="ES256",
                      headers={"kid": settings.apple_devicecheck_key_id})


def _apple_body(token: str) -> dict:
    return {"device_token": token, "transaction_id": uuid.uuid4().hex, "timestamp": int(time.time() * 1000)}


def _apple_query(token: str) -> DeviceVerdict:
    base = APPLE_DEVICECHECK.get(settings.apple_environment, APPLE_DEVICECHECK["Sandbox"])
    with store_billing._client() as c:
        r = c.post(f"{base}/query_two_bits", json=_apple_body(token),
                   headers={"Authorization": f"Bearer {_apple_jwt()}"})
    if r.status_code != 200:
        return _unavailable(f"DeviceCheck ответил {r.status_code}")
    if not r.content or not r.text.lstrip().startswith("{"):
        return DeviceVerdict(available=True, trial_used=False)  # «Failed to find bit state» — биты не ставились
    return DeviceVerdict(available=True, trial_used=bool(r.json().get("bit0")))


def _apple_update(token: str) -> None:
    base = APPLE_DEVICECHECK.get(settings.apple_environment, APPLE_DEVICECHECK["Sandbox"])
    with store_billing._client() as c:
        r = c.post(f"{base}/update_two_bits", json={**_apple_body(token), "bit0": True, "bit1": False},
                   headers={"Authorization": f"Bearer {_apple_jwt()}"})
    r.raise_for_status()


# ---------- Google Play Integrity, device recall ----------

def _google_query(token: str) -> DeviceVerdict:
    pkg = settings.google_package_name
    with store_billing._client() as c:
        r = c.post(f"{PLAY_INTEGRITY}/{pkg}:decodeIntegrityToken", json={"integrityToken": token},
                   headers={"Authorization": f"Bearer {store_billing.google_access_token(PLAY_INTEGRITY_SCOPE)}"})
    if r.status_code != 200:
        return _unavailable(f"Play Integrity ответил {r.status_code}")
    payload = r.json().get("tokenPayloadExternal") or {}
    if (payload.get("appIntegrity") or {}).get("packageName") not in (None, pkg):
        return _unavailable("токен другого приложения")
    device = payload.get("deviceIntegrity") or {}
    if "MEETS_DEVICE_INTEGRITY" not in (device.get("deviceRecognitionVerdict") or []):
        return _unavailable("телефон не прошёл проверку целостности (эмулятор или изменённая система)")
    values = (device.get("deviceRecall") or {}).get("values") or {}
    return DeviceVerdict(available=True, trial_used=bool(values.get("bitFirst")))


def _google_write(token: str) -> None:
    pkg = settings.google_package_name
    with store_billing._client() as c:
        r = c.post(f"{PLAY_INTEGRITY}/{pkg}/deviceRecall:write",
                   json={"integrityToken": token, "newValues": {"bitFirst": True}},
                   headers={"Authorization": f"Bearer {store_billing.google_access_token(PLAY_INTEGRITY_SCOPE)}"})
    r.raise_for_status()
