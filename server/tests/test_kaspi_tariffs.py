"""К-33 А2: тарифы Kaspi 2026 — каждая ставка и строка тарифа, пороги 5 000 и 10 000 ₸, плательщик и неплательщик НДС."""

import pytest

from app import kaspi_tariffs as kt

T = 100  # тиынов в тенге


@pytest.mark.parametrize("with_vat,net,promo", [(730, 640, 770), (1250, 1090, 1300), (1550, 1350, 1610)])
def test_commission_pairs_from_kaspi_table(with_vat, net, promo):
    assert kt.net_rate_bp(with_vat) == net
    assert kt.promo_rate_bp(with_vat) == promo
    assert kt.tier_for_rate(promo).rate_bp == with_vat


def test_net_rate_is_not_divided_by_1_16():
    # 12,5 / 1,16 = 10,78 %, а у Kaspi — 10,9 %
    assert kt.net_rate_bp(1250) == 1090 != round(1250 / 1.16)


def test_custom_rate_uses_main_group_ratio():
    assert kt.net_rate_bp(1000) == 872  # 10 × 10,9 / 12,5 = 8,72
    assert kt.promo_rate_bp(1000) == 1050


@pytest.mark.parametrize("order_sum,city,kz", [
    (1, 49, 49), (999, 49, 49), (1_000, 149, 149), (2_999, 149, 149), (3_000, 199, 199), (4_999, 199, 199),
    (5_000, 699, 799), (9_999, 699, 799),
])
def test_small_order_tariff_rows(order_sum, city, kz):
    assert kt.delivery_tariff_tenge(order_sum, "city") == city
    assert kt.delivery_tariff_tenge(order_sum, "kz") == kz
    assert kt.delivery_tariff_tenge(order_sum, "express") == kz


@pytest.mark.parametrize("weight,city,kz,express", [
    (1, 1_099, 1_299, 1_699), (5, 1_099, 1_299, 1_699), (5.1, 1_349, 1_699, 1_849), (15, 1_349, 1_699, 1_849),
    (30, 2_299, 3_599, 3_149), (60, 2_899, 5_649, 3_599), (100, 4_149, 8_549, 5_599), (101, 6_449, 11_999, 8_449),
])
def test_weight_tariff_rows_from_10000(weight, city, kz, express):
    assert kt.delivery_tariff_tenge(10_000, "city", weight) == city
    assert kt.delivery_tariff_tenge(25_000, "kz", weight) == kz
    assert kt.delivery_tariff_tenge(10_000, "express", weight) == express


def test_unknown_weight_counts_as_lightest():
    assert kt.delivery_tariff_tenge(15_000, "city", None) == 1_099


def test_non_payer_profit_formula():
    e = kt.unit_profit(4_990 * T, 3_000 * T, 1250)
    assert e.commission_minor == 62_375  # 4 990 × 12,5 % = 623,75 ₸
    assert e.delivery_minor == 23_084  # 199 ₸ × 1,16
    assert e.profit_minor == 4_990 * T - 62_375 - 23_084 - 3_000 * T


def test_vat_payer_profit_formula():
    e = kt.unit_profit(5_800 * T, 3_000 * T, 1250, vat_payer=True)
    assert e.revenue_minor == 5_000 * T  # 5 800 / 1,16
    assert e.commission_minor == 63_220  # 5 800 × 10,9 %
    assert e.delivery_minor == 699 * T  # без НДС
    assert e.profit_minor == 5_000 * T - 63_220 - 699 * T - 3_000 * T


def test_tax_from_revenue():
    assert kt.unit_profit(10_000 * T, 0, 1250, tax_bp=300).tax_minor == 300 * T
    assert kt.unit_profit(11_600 * T, 0, 1250, tax_bp=300, vat_payer=True).tax_minor == 300 * T


def test_threshold_example_from_owner():
    # 5 200 ₸ вместо 4 990 ₸ при 12,5 % — продавцу примерно на 400 ₸ меньше с заказа
    hint = kt.threshold_hint(5_200 * T, 3_000 * T, 1250)
    assert hint is not None and hint.threshold_tenge == 5_000 and hint.suggested_price_minor == 4_990 * T
    assert 390 * T <= hint.gain_minor <= 400 * T


def test_no_hint_far_above_threshold_or_below():
    assert kt.threshold_hint(7_000 * T, 3_000 * T, 1250) is None
    assert kt.threshold_hint(4_500 * T, 3_000 * T, 1250) is None


def test_hint_at_10000_threshold():
    hint = kt.threshold_hint(10_100 * T, 5_000 * T, 1250, weight_kg=2)
    assert hint is not None and hint.threshold_tenge == 10_000


@pytest.mark.parametrize("cost", [0, 100 * T, 3_000 * T, 4_300 * T, 8_000 * T, 20_000 * T])
@pytest.mark.parametrize("vat_payer", [False, True])
@pytest.mark.parametrize("rate", [730, 1250, 1300, 1610])
def test_min_price_is_exact(cost, vat_payer, rate):
    p = kt.min_price_no_loss(cost, rate, vat_payer=vat_payer)
    assert p % T == 0
    assert kt.unit_profit(p, cost, rate, vat_payer=vat_payer).profit_minor >= 0
    # ни одна более низкая цена (с шагом 1 ₸) не безубыточна — проверяем окрестность и пороги ниже
    for lower in [p - T, *(t * T - T for t in kt.DELIVERY_THRESHOLDS if t * T < p)]:
        if lower > 0:
            assert kt.unit_profit(lower, cost, rate, vat_payer=vat_payer).profit_minor < 0


def test_min_price_jumps_over_threshold_trap():
    # себестоимость 4 300 ₸: в диапазоне до 5 000 ₸ не хватает, выше 5 000 ₸ доставка 699 ₸ — цена заметно выше
    p = kt.min_price_no_loss(4_300 * T, 1250)
    assert p > 5_000 * T


def test_vat_helpers():
    assert kt.with_vat(199 * T) == 23_084
    assert kt.without_vat(11_600 * T) == 10_000 * T
