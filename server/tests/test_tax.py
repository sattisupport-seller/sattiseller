"""Налог (ТЗ 2.1, раздел 7.4). Отдельный набор: G001–G008 из 2.0 не меняются.

Все суммы в тиынах (1 ₸ = 100). Комиссия 10% = 1000 bp, налог 4% = 400 bp.
"""

import pytest

from app.finance import Return, SaleLine, calc_line, sale_result
from app.money import apply_bp

T = 100
COMMISSION_10 = 1000
TAX_4 = 400


def _ret(**kw) -> Return:
    base = dict(
        returned_qty=1,
        refund_minor=None,
        commission_returned_minor=None,
        delivery_returned_minor=None,
        reverse_delivery_minor=None,
        goods_sellable=None,
        tax_returned_minor=0,
    )
    base.update(kw)
    return Return(**base)


def g009() -> SaleLine:
    # 1 шт. × 10 000 ₸; закупка 6 000 ₸; комиссия 10%; доставка 0; налог 4%
    return SaleLine(qty=1, unit_price_minor=10_000 * T, status="completed",
                    unit_cost_minor=6_000 * T, buyer_delivery_minor=0,
                    commission_rate_bp=COMMISSION_10, tax_rate_bp=TAX_4)


def g010() -> SaleLine:
    # как G004 (3 000 ₸; закупка 1 200 ₸; доставка 100 ₸; полный возврат; комиссия и доставка возвращены;
    # товар годен) плюс налог 4%: налог продажи 120 ₸, налог возврата −120 ₸
    tax_on_refund = apply_bp(3_000 * T, TAX_4)
    return SaleLine(qty=1, unit_price_minor=3_000 * T, status="completed",
                    unit_cost_minor=1_200 * T, buyer_delivery_minor=100 * T,
                    commission_rate_bp=COMMISSION_10, tax_rate_bp=TAX_4,
                    returns=[_ret(refund_minor=3_000 * T, commission_returned_minor=300 * T,
                                  delivery_returned_minor=100 * T, reverse_delivery_minor=0,
                                  goods_sellable=True, tax_returned_minor=tax_on_refund)])


def test_g009_tax_reduces_profit():
    sale = sale_result(g009())
    assert sale.commission_minor == 1_000 * T
    assert sale.tax_minor == 400 * T
    assert sale.profit_minor == 2_600 * T


def test_g010_tax_on_sale_and_refund_cancel_out():
    assert sale_result(g010()).tax_minor == 120 * T
    res = calc_line(g010())
    assert res.is_complete
    assert res.profit_minor == 0


def test_r004_half_up_on_tax():
    # 1 шт. × 333 ₸; налог 1,5% → 33 300 × 150 / 10 000 = 499,5 тиына → 500 тиынов
    line = SaleLine(qty=1, unit_price_minor=333 * T, status="completed", unit_cost_minor=None,
                    buyer_delivery_minor=0, commission_rate_bp=None, tax_rate_bp=150)
    assert sale_result(line).tax_minor == 500


def test_no_tax_rate_means_no_tax_line():
    # ставка не задана — налога нет, прибыль как в 2.0
    line = SaleLine(qty=1, unit_price_minor=10_000 * T, status="completed",
                    unit_cost_minor=6_000 * T, buyer_delivery_minor=0,
                    commission_rate_bp=COMMISSION_10, tax_rate_bp=None)
    sale = sale_result(line)
    assert sale.tax_minor == 0
    assert sale.profit_minor == 3_000 * T


@pytest.mark.parametrize("rate", [0, 1])
def test_zero_rate_is_zero_tax(rate):
    line = SaleLine(qty=1, unit_price_minor=1_000 * T, status="completed", unit_cost_minor=500 * T,
                    buyer_delivery_minor=0, commission_rate_bp=0, tax_rate_bp=rate)
    assert sale_result(line).tax_minor == apply_bp(1_000 * T, rate)
