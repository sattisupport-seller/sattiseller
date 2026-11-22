"""Единая функция текущего времени (UTC). В БД хранятся значения с часовым поясом (CLAUDE.md, «Время»).

Модули, которым нужно «сейчас», вызывают utc_now() через свои локальные имена (например, _now),
поэтому тесты подменяют время в конкретном модуле, как и раньше.
"""

from datetime import datetime, timezone


def utc_now() -> datetime:
    return datetime.now(timezone.utc)
