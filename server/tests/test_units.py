"""Юнит-проверки: разложение прибыли по периодам, периоды, деньги, импорт (правила раздела 7)."""

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from app.finance import Return, SaleLine, calc_line, return_profit_delta, sale_result
from app.imports import parse_money_cell, parse_sku_cell
from app.money import format_tenge, parse_tenge_to_minor
from app.periods import PeriodError, resolve
from tests.test_golden import g001, g004, g006, g007


@pytest.mark.parametrize("line", [g001(), g004(), g006(), g007()], ids=["G001", "G004", "G006", "G007"])
def test_sale_plus_return_deltas_equal_lifetime_profit(line):
    """Прибыль по периодам (продажа в одном периоде, возврат в другом) даёт тот же итог, что и за всё время."""
    sale = sale_result(SaleLine(**{**line.__dict__, "returns": []}))
    total = sale.profit_minor
    for r in line.returns:
        total += return_profit_delta(line, r)
    assert total == calc_line(line).profit_minor


def test_unknown_return_component_makes_line_incomplete():
    line = SaleLine(qty=1, unit_price_minor=300000, status="completed", unit_cost_minor=120000,
                    buyer_delivery_minor=10000, commission_rate_bp=1000,
                    returns=[Return(1, 300000, None, 0, 0, True)])
    res = calc_line(line)
    assert res.is_complete is False
    assert res.profit_minor is None


def test_missing_commission_rate_is_unknown_not_zero():
    line = SaleLine(qty=1, unit_price_minor=300000, status="completed", unit_cost_minor=120000,
                    buyer_delivery_minor=10000, commission_rate_bp=None)
    assert calc_line(line).profit_minor is None


def test_period_presets_are_inclusive_and_timezone_aware():
    now = datetime(2026, 11, 19, 12, 0, tzinfo=timezone.utc)  # в Алматы уже 19 ноября
    p7 = resolve("7d", "Asia/Almaty", now)
    assert p7.start == date(2026, 11, 13) and p7.end == date(2026, 11, 19) and p7.days == 7
    prev = p7.previous_equal()
    assert prev.start == date(2026, 11, 6) and prev.end == date(2026, 11, 12)
    assert resolve("yesterday", "Asia/Almaty", now).start == date(2026, 11, 18)
    assert resolve("previous_month", "Asia/Almaty", now).start == date(2026, 10, 1)


def test_custom_period_validation():
    with pytest.raises(PeriodError):
        resolve("2026-11-10..2026-11-01", "Asia/Almaty")
    with pytest.raises(PeriodError):
        resolve("nonsense", "Asia/Almaty")


def test_money_formatting_matches_spec():
    assert format_tenge(124530000) == "1 245 300 ₸"
    assert format_tenge(-860000) == "−8 600 ₸"
    assert format_tenge(9600) == "96 ₸"


def test_parse_money_rules():
    assert parse_money_cell("2 800 ₸", True) == (280000, None)
    assert parse_money_cell("1 200,5", True) == (120050, None)
    assert parse_money_cell("1 200,505", True)[1] == "Больше двух знаков после запятой"
    assert parse_money_cell("-500", True)[1] == "Отрицательные значения не допускаются"
    assert parse_money_cell(None, True)[1] == "Не заполнено обязательное значение"
    assert parse_money_cell(None, False) == (None, None)
    assert parse_money_cell(2800.0, True)[0] == 280000


def test_sku_rules():
    assert parse_sku_cell("D007") == ("D007", None)
    assert parse_sku_cell(12345.0) == ("12345", None)
    assert parse_sku_cell("4,6E+12")[1].startswith("Артикул испорчен Excel")  # текст в экспоненте — ошибка
    assert parse_sku_cell("4.6E+12")[1].startswith("Артикул испорчен Excel")
    assert parse_sku_cell(4.6e12) == ("4600000000000", None)  # числовая ячейка без «.0» — ок


def test_parse_tenge_decimal_only():
    assert parse_tenge_to_minor(Decimal("0.01")) == 1
    with pytest.raises(ValueError):
        parse_tenge_to_minor("0.001")
