"""Золотой набор из docs/spec.md, раздел 6.6. Ожидаемые значения — из ТЗ, не из кода.

Все суммы в тиынах (1 ₸ = 100). Комиссия 10% = 1000 bp, если не указано иное.
"""

import pytest

from app.finance import Return, SaleLine, calc_line, calc_totals
from app.money import format_tenge, parse_tenge_to_minor

COMMISSION_10 = 1000
T = 100  # тиын в тенге


def _ret(**kw) -> Return:
    base = dict(
        returned_qty=1,
        refund_minor=None,
        commission_returned_minor=None,
        delivery_returned_minor=None,
        reverse_delivery_minor=None,
        goods_sellable=None,
    )
    base.update(kw)
    return Return(**base)


def g001() -> SaleLine:
    # 2 шт. × 2 000 ₸; закупка 1 000 ₸/шт; доставка 100 ₸/шт → на строку 200 ₸
    return SaleLine(qty=2, unit_price_minor=2000 * T, status="completed",
                    unit_cost_minor=1000 * T, buyer_delivery_minor=200 * T,
                    commission_rate_bp=COMMISSION_10)


def g002() -> SaleLine:
    return SaleLine(qty=1, unit_price_minor=2000 * T, status="completed",
                    unit_cost_minor=2400 * T, buyer_delivery_minor=100 * T,
                    commission_rate_bp=COMMISSION_10)


def g003() -> SaleLine:
    return SaleLine(qty=1, unit_price_minor=2000 * T, status="cancelled",
                    unit_cost_minor=1000 * T, buyer_delivery_minor=100 * T,
                    commission_rate_bp=COMMISSION_10)


def g004() -> SaleLine:
    # полный возврат; комиссия 300 ₸ и доставка 100 ₸ возвращены; товар годен
    return SaleLine(qty=1, unit_price_minor=3000 * T, status="completed",
                    unit_cost_minor=1200 * T, buyer_delivery_minor=100 * T,
                    commission_rate_bp=COMMISSION_10,
                    returns=[_ret(refund_minor=3000 * T, commission_returned_minor=300 * T,
                                  delivery_returned_minor=100 * T, reverse_delivery_minor=0,
                                  goods_sellable=True)])


def g005() -> SaleLine:
    # закупка не задана → прибыль unknown
    return SaleLine(qty=1, unit_price_minor=1500 * T, status="completed",
                    unit_cost_minor=None, buyer_delivery_minor=100 * T,
                    commission_rate_bp=COMMISSION_10)


def g006() -> SaleLine:
    # полный возврат; комиссия возвращена, доставка не возвращена, обратная доставка 100 ₸, товар годен
    return SaleLine(qty=1, unit_price_minor=3000 * T, status="completed",
                    unit_cost_minor=1200 * T, buyer_delivery_minor=100 * T,
                    commission_rate_bp=COMMISSION_10,
                    returns=[_ret(refund_minor=3000 * T, commission_returned_minor=300 * T,
                                  delivery_returned_minor=0, reverse_delivery_minor=100 * T,
                                  goods_sellable=True)])


def g007() -> SaleLine:
    # 3 шт. × 1 000 ₸ одной строкой; закупка 400 ₸/шт; доставка 150 ₸ за строку;
    # возврат 1 шт., комиссия 100 ₸ возвращена, доставка не возвращена, товар годен
    return SaleLine(qty=3, unit_price_minor=1000 * T, status="completed",
                    unit_cost_minor=400 * T, buyer_delivery_minor=150 * T,
                    commission_rate_bp=COMMISSION_10,
                    returns=[_ret(returned_qty=1, refund_minor=1000 * T,
                                  commission_returned_minor=100 * T,
                                  delivery_returned_minor=0, reverse_delivery_minor=0,
                                  goods_sellable=True)])


def g008_first() -> SaleLine:
    # 03.11: закупка 1 000 ₸ (версия с начала истории), доставка 100 ₸
    return SaleLine(qty=1, unit_price_minor=2000 * T, status="completed",
                    unit_cost_minor=1000 * T, buyer_delivery_minor=100 * T,
                    commission_rate_bp=COMMISSION_10)


def g008_second() -> SaleLine:
    # 12.11: закупка 1 300 ₸ (версия с 10.11), доставка 100 ₸
    return SaleLine(qty=1, unit_price_minor=2000 * T, status="completed",
                    unit_cost_minor=1300 * T, buyer_delivery_minor=100 * T,
                    commission_rate_bp=COMMISSION_10)


@pytest.mark.parametrize(
    "line, expected_profit",
    [
        (g001(), 1400 * T),
        (g002(), -700 * T),
        (g003(), 0),
        (g004(), 0),
        (g006(), -200 * T),
        (g007(), 850 * T),
        (g008_first(), 700 * T),
        (g008_second(), 400 * T),
    ],
    ids=["G001", "G002", "G003", "G004", "G006", "G007", "G008a", "G008b"],
)
def test_golden_line_profit(line, expected_profit):
    res = calc_line(line)
    assert res.is_complete
    assert res.profit_minor == expected_profit


def test_g005_unknown_cost_is_not_zero():
    res = calc_line(g005())
    assert res.profit_minor is None
    assert res.is_complete is False
    assert res.net_sales_minor == 1500 * T


def test_g001_components():
    res = calc_line(g001())
    assert res.net_sales_minor == 4000 * T


def test_golden_aggregate_g001_g008():
    lines = [g001(), g002(), g003(), g004(), g005(), g006(), g007(),
             g008_first(), g008_second()]
    totals = calc_totals(lines)
    assert totals.orders_minor == 22500 * T
    assert totals.completed_gross_minor == 20500 * T
    assert totals.returns_minor == 7000 * T
    assert totals.cancelled_minor == 2000 * T
    assert totals.net_sales_all_minor == 13500 * T
    assert totals.net_sales_complete_minor == 12000 * T
    assert totals.profit_minor == 2450 * T
    assert totals.coverage_bp == 8889  # 88,9%
    assert totals.margin_bp == 2042  # 20,4% (не 18,1%)


def test_rounding_r001_commission_half_up():
    # 1 шт. × 999 ₸, комиссия 7,5% (750 bp), себестоимость 500 ₸
    line = SaleLine(qty=1, unit_price_minor=99900, status="completed",
                    unit_cost_minor=50000, buyer_delivery_minor=0,
                    commission_rate_bp=750)
    res = calc_line(line)
    assert res.profit_minor == 42407  # комиссия 7 493, не 7 492
    assert format_tenge(res.profit_minor) == "424 ₸"


def test_rounding_r002_half_up_on_screen():
    assert format_tenge(42450) == "425 ₸"


def test_rounding_r003_negative_half_away_from_zero():
    assert format_tenge(-42450) == "−425 ₸"


def test_parse_tenge_rejects_fractional_tiyn():
    assert parse_tenge_to_minor("999.99") == 99999
    with pytest.raises(ValueError):
        parse_tenge_to_minor("1.001")


def test_parse_tenge_accepts_no_float_artifacts():
    # 0.1 + 0.2 как float не должно просочиться в деньги
    assert parse_tenge_to_minor("0.3") == 30
