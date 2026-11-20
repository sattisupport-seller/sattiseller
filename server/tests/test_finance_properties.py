"""QA этап 2: свойства финансовых расчётов (hypothesis) и крайние случаи.

Суммы в тиынах (int). Ставки в базисных пунктах (10000 = 100%).
"""

from decimal import ROUND_HALF_UP, Decimal

from hypothesis import given, settings, strategies as st

from app.finance import Return, SaleLine, calc_line, calc_totals, sale_result
from app.money import apply_bp, format_tenge, round_half_up_div

money = st.integers(min_value=0, max_value=10**12)
qty = st.integers(min_value=1, max_value=1000)
bp = st.integers(min_value=0, max_value=3000)  # комиссия/налог до 30%


def _line(price, n, cost, delivery, commission_bp, tax_bp=None, status="completed", returns=None):
    return SaleLine(qty=n, unit_price_minor=price, status=status, unit_cost_minor=cost,
                    buyer_delivery_minor=delivery, commission_rate_bp=commission_bp,
                    returns=returns or [], tax_rate_bp=tax_bp)


# ---------- округления ----------

@settings(max_examples=500)
@given(st.integers(min_value=-10**15, max_value=10**15), st.integers(min_value=1, max_value=10**6))
def test_round_half_up_div_matches_decimal(a, b):
    exact = Decimal(a) / Decimal(b)
    expected = int(exact.quantize(Decimal(1), rounding=ROUND_HALF_UP))
    assert round_half_up_div(a, b) == expected


@settings(max_examples=500)
@given(money, bp)
def test_apply_bp_is_within_half_a_tiyn_of_exact_share(amount, rate):
    exact = Decimal(amount) * Decimal(rate) / Decimal(10000)
    assert abs(Decimal(apply_bp(amount, rate)) - exact) <= Decimal("0.5")


@settings(max_examples=300)
@given(st.integers(min_value=-10**13, max_value=10**13))
def test_format_tenge_is_rounded_and_grouped(minor):
    text = format_tenge(minor).replace("−", "-")
    text = "".join(ch for ch in text if ch.isdigit() or ch == "-")
    value = int(text)
    assert abs(value * 100 - minor) <= 50  # не дальше половины тенге от точной суммы (в тиынах)


# ---------- прибыль продажи ----------

@settings(max_examples=400)
@given(money, qty, money, money, bp, bp)
def test_profit_identity_for_complete_sale(price, n, cost, delivery, commission_bp, tax_bp):
    line = _line(price, n, cost, delivery, commission_bp, tax_bp)
    res = sale_result(line)
    assert res.profit_minor == res.gross_minor - res.landed_minor - res.commission_minor - res.delivery_minor - res.tax_minor


@settings(max_examples=300)
@given(money, qty, money, money, bp, st.integers(min_value=1, max_value=10**6))
def test_higher_unit_cost_never_increases_profit(price, n, cost, delivery, commission_bp, extra):
    low = calc_line(_line(price, n, cost, delivery, commission_bp)).profit_minor
    high = calc_line(_line(price, n, cost + extra, delivery, commission_bp)).profit_minor
    assert high <= low


# ---------- возврат ----------

@settings(max_examples=300)
@given(money, qty, money, money, bp, bp)
def test_full_return_with_everything_recovered_leaves_zero_profit(price, n, cost, delivery, commission_bp, tax_bp):
    gross = price * n
    sale = sale_result(_line(price, n, cost, delivery, commission_bp, tax_bp))
    ret = Return(returned_qty=n, refund_minor=gross, commission_returned_minor=sale.commission_minor,
                 delivery_returned_minor=delivery, reverse_delivery_minor=0,  # как G004 из ТЗ: доставка возвращена
                 goods_sellable=True, tax_returned_minor=sale.tax_minor)
    res = calc_line(_line(price, n, cost, delivery, commission_bp, tax_bp, returns=[ret]))
    assert res.profit_minor == 0
    assert res.net_sales_minor == 0


# ---------- крайние случаи (точечные) ----------

def test_zero_price_sale_has_zero_gross_and_negative_profit_from_costs():
    res = calc_line(_line(0, 3, 500, 100, 1000))
    assert res.net_sales_minor == 0
    assert res.profit_minor == -(500 * 3 + 100)  # комиссия от нуля = 0


def test_partial_return_recovers_only_returned_units():
    line = _line(10_000, 4, 4_000, 0, 0, returns=[
        Return(returned_qty=1, refund_minor=10_000, commission_returned_minor=0,
               delivery_returned_minor=0, reverse_delivery_minor=0, goods_sellable=True)])
    res = calc_line(line)
    # продано 4 на 40 000, вернули 1 за 10 000 (товар годен — себестоимость 4 000 возвращена)
    assert res.net_sales_minor == 30_000
    assert res.profit_minor == (40_000 - 16_000) - 10_000 + 4_000


def test_return_of_damaged_goods_does_not_recover_cost():
    line = _line(10_000, 1, 4_000, 0, 0, returns=[
        Return(returned_qty=1, refund_minor=10_000, commission_returned_minor=0,
               delivery_returned_minor=0, reverse_delivery_minor=0, goods_sellable=False)])
    assert calc_line(line).profit_minor == (10_000 - 4_000) - 10_000


def test_negative_profit_is_reported_not_clamped():
    res = calc_line(_line(1_000, 1, 5_000, 0, 0))
    assert res.profit_minor == -4_000


def test_large_amounts_stay_exact():
    big = 10**12  # 10 млрд тенге в тиынах
    res = calc_line(_line(big, 1000, 999_999_999_999, 0, 1234))
    assert res.profit_minor == big * 1000 - 999_999_999_999 * 1000 - apply_bp(big * 1000, 1234)


def test_unknown_cost_makes_line_incomplete_not_zero():
    res = calc_line(_line(10_000, 2, None, 0, 1000))
    assert res.is_complete is False
    assert res.profit_minor is None


def test_cancelled_line_contributes_nothing_to_totals():
    lines = [_line(10_000, 1, 2_000, 0, 1000, status="cancelled"), _line(10_000, 1, 2_000, 0, 1000)]
    t = calc_totals(lines)
    assert t.cancelled_minor == 10_000
    assert t.net_sales_all_minor == 10_000
