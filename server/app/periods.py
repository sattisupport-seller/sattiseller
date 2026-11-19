"""Календарные периоды в часовом поясе магазина (docs/spec.md, разделы 5.1 и 10)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

PRESETS = {
    "today": 0,
    "7d": 7,
    "last_7_days": 7,
    "14d": 14,
    "last_14_days": 14,
    "30d": 30,
    "last_30_days": 30,
    "90d": 90,
    "last_90_days": 90,
}


@dataclass(frozen=True)
class Period:
    start: date  # включительно
    end: date  # включительно

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1

    def contains(self, day: date) -> bool:
        return self.start <= day <= self.end

    def previous_equal(self) -> "Period":
        length = self.days
        return Period(self.start - timedelta(days=length), self.start - timedelta(days=1))


class PeriodError(ValueError):
    pass


def today_in(tz_name: str, now: datetime | None = None) -> date:
    tz = ZoneInfo(tz_name)
    current = now.astimezone(tz) if now else datetime.now(tz)
    return current.date()


def resolve(name: str, tz_name: str, now: datetime | None = None) -> Period:
    """name: пресет (today, 7d, 30d, 90d, yesterday, this_month, previous_month) или 'YYYY-MM-DD..YYYY-MM-DD'."""
    today = today_in(tz_name, now)
    if ".." in name:
        a, _, b = name.partition("..")
        try:
            start, end = date.fromisoformat(a), date.fromisoformat(b)
        except ValueError as exc:
            raise PeriodError("неверный формат дат") from exc
        if end < start:
            raise PeriodError("конец периода раньше начала")
        if (end - start).days > 366:
            raise PeriodError("период длиннее года")
        return Period(start, end)
    if name in PRESETS:
        n = PRESETS[name]  # число дней включая сегодня: 7d = сегодня и 6 предыдущих
        return Period(today - timedelta(days=max(n - 1, 0)), today)
    if name == "yesterday":
        y = today - timedelta(days=1)
        return Period(y, y)
    if name == "this_month":
        return Period(today.replace(day=1), today)
    if name == "previous_month":
        first_this = today.replace(day=1)
        last_prev = first_this - timedelta(days=1)
        return Period(last_prev.replace(day=1), last_prev)
    raise PeriodError(f"неизвестный период: {name}")
