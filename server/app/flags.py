"""Флаги функций. Значение — из базы (админка), по умолчанию — из FLAG_DEFAULTS.

Выключатель ИИ (ТЗ 2.1, 11.2: «срабатывает сразу»): при выключенном флаге помощник и черновики отвечают 503,
приложение получает флаг из /app/config и показывает сообщение вместо экрана помощника.
"""

from __future__ import annotations

from sqlalchemy.orm import Session as DbSession

from .admin import FLAG_DEFAULTS, FeatureFlag
from .errors import ApiError

AI_OFF_MESSAGE = "Помощник временно недоступен. Отчёты работают как обычно."


def is_enabled(db: DbSession, key: str) -> bool:
    row = db.get(FeatureFlag, key)
    if row is not None:
        return bool(row.enabled)
    return bool(FLAG_DEFAULTS.get(key, False))


def require_ai(db: DbSession) -> None:
    """Проверка выключателя ИИ. Поднимает 503 с понятным текстом, если помощник выключен."""
    if not is_enabled(db, "ai_assistant"):
        raise ApiError(503, "ai_disabled", AI_OFF_MESSAGE)
