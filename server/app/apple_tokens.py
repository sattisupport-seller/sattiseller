"""Sign in with Apple: обмен кода на refresh token и его отзыв при удалении аккаунта (MASTER_PLAN 3.3, К-21).

Apple требует: если в приложении есть вход через Apple и удаление аккаунта, при удалении нужно отозвать токены
пользователя через REST API (`/auth/revoke`). Для отзыва нужен refresh token — его даёт только обмен
authorizationCode при входе (`/auth/token`). Токен хранится зашифрованным, как ключ Kaspi.

client_secret — JWT ES256 ключом Sign in with Apple (Certificates, Identifiers & Profiles → Keys):
iss = Team ID, sub = client_id (bundle id), aud = https://appleid.apple.com, срок — 5 минут.
Без ключа (разработка, тесты без моков) обмен и отзыв пропускаются с записью в журнал — вход и удаление работают.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

import httpx
import jwt

from .config import settings

log = logging.getLogger("satti.apple")
TOKEN_URL = "https://appleid.apple.com/auth/token"
REVOKE_URL = "https://appleid.apple.com/auth/revoke"
transport: httpx.BaseTransport | None = None  # в тестах — httpx.MockTransport


def configured() -> bool:
    return bool(settings.apple_team_id and settings.apple_siwa_key_id and settings.apple_siwa_key_path)


def client_secret(now: float | None = None) -> str:
    now = now or time.time()
    key = Path(settings.apple_siwa_key_path).read_text(encoding="utf-8")
    return jwt.encode({"iss": settings.apple_team_id, "iat": int(now), "exp": int(now) + 300,
                       "aud": "https://appleid.apple.com", "sub": settings.apple_client_id},
                      key, algorithm="ES256", headers={"kid": settings.apple_siwa_key_id})


def exchange_code(code: str) -> str | None:
    """authorizationCode → refresh token. Ошибка не мешает входу: токен личности уже проверен."""
    if not configured() or not code:
        if code:
            log.info("apple code exchange skipped: Sign in with Apple key is not configured")
        return None
    try:
        with httpx.Client(timeout=10.0, transport=transport) as http:
            r = http.post(TOKEN_URL, data={"client_id": settings.apple_client_id, "client_secret": client_secret(),
                                           "code": code, "grant_type": "authorization_code"})
    except httpx.HTTPError as exc:
        log.warning("apple code exchange failed: %s", type(exc).__name__)
        return None
    if r.status_code != 200:
        log.warning("apple code exchange refused: %s", r.status_code)  # без тела: там может быть код
        return None
    return r.json().get("refresh_token")


def revoke(refresh_token: str) -> bool:
    """Отзыв при удалении аккаунта. Сбой не останавливает удаление (данные удаляем в любом случае), пишем в журнал."""
    if not configured():
        log.warning("apple token revoke skipped: Sign in with Apple key is not configured")
        return False
    try:
        with httpx.Client(timeout=10.0, transport=transport) as http:
            r = http.post(REVOKE_URL, data={"client_id": settings.apple_client_id, "client_secret": client_secret(),
                                            "token": refresh_token, "token_type_hint": "refresh_token"})
    except httpx.HTTPError as exc:
        log.warning("apple token revoke failed: %s", type(exc).__name__)
        return False
    if r.status_code != 200:
        log.warning("apple token revoke refused: %s", r.status_code)
        return False
    return True
