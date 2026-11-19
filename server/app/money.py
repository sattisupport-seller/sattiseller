"""Деньги: целые тиыны (int), ставки в базисных пунктах (int), ROUND_HALF_UP.

float для денег запрещён: входные значения разбираются через Decimal(str(value)).
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

TIYN_PER_TENGE = 100
BP_DENOMINATOR = 10_000


def parse_tenge_to_minor(value: str | int | Decimal) -> int:
    """Перевести сумму в тенге в тиыны. Дробной части тиынов быть не должно."""
    try:
        dec = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError(f"некорректная сумма: {value!r}") from exc
    minor = dec * TIYN_PER_TENGE
    if minor != minor.to_integral_value():
        raise ValueError(f"сумма имеет дробную часть тиынов: {value!r}")
    return int(minor)


def round_half_up_div(numerator: int, denominator: int) -> int:
    """Деление с округлением половины от нуля (как в Excel)."""
    if denominator == 0:
        raise ValueError("деление на ноль")
    sign = (-1 if numerator < 0 else 1) * (-1 if denominator < 0 else 1)
    quotient = (Decimal(abs(numerator)) / Decimal(abs(denominator))).quantize(
        Decimal(1), rounding=ROUND_HALF_UP
    )
    return sign * int(quotient)


def apply_bp(amount_minor: int, rate_bp: int) -> int:
    """Доля суммы в базисных пунктах, округление ROUND_HALF_UP до тиына."""
    if rate_bp < 0:
        raise ValueError("ставка не может быть отрицательной")
    return round_half_up_div(amount_minor * rate_bp, BP_DENOMINATOR)


def format_tenge(minor: int) -> str:
    """Отображение целых тенге: '1 245 300 ₸', минус — U+2212, округление ROUND_HALF_UP."""
    sign = "−" if minor < 0 else ""
    tenge = round_half_up_div(abs(minor), TIYN_PER_TENGE)
    digits = f"{tenge:,}".replace(",", " ")
    return f"{sign}{digits} ₸"
