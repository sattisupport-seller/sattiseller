"""Тарифы Kaspi 2026 и расчёты «языком денег» (К-33, А2). Все суммы — целые тиыны, ставки — базисные пункты.

Источники (проверены координатором по гиду Kaspi 28.11.2026):
- комиссия: документ Kaspi «Тарифы Магазина на Kaspi.kz с 5 января 2026 года» — ставки без НДС → с НДС:
  6,4 → 7,3 %; 10,9 → 12,5 %; 13,5 → 15,5 % (по категории товара);
- акции с рассрочкой 0-0-24: гид q1344, пример — гид q4591 (бытовая техника в акции — 13 % с НДС);
  ставки по умолчанию 7,7 / 13,0 / 16,1 % с НДС (данные владельца), продавец может поправить;
- доставка: гид q2288 «Тарифы Kaspi Доставки с 01.01.2026», обновлен 16.06.2026; суммы без НДС,
  продавцу списываются с НДС и только когда заказ «Выдан».

Не считать «без НДС × 1,16»: у Kaspi отношение ≈ 1,14–1,15 (НДС начисляется не на всю комиссию). Поэтому
ставки с НДС и без НДС берутся парами из таблицы, а не пересчитываются.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .money import apply_bp, round_half_up_div

VAT_BP = 1600  # НДС Казахстана с 2026 года — 16 %
DELIVERY_FACT_INCLUDES_VAT = False  # deliveryCostForSeller — тариф без НДС (допущение; проверить: KASPI_TEST.md)

Zone = Literal["city", "kz", "express"]


@dataclass(frozen=True)
class CommissionTier:
    key: str
    title: str
    rate_bp: int  # обычная ставка с НДС
    rate_net_bp: int  # обычная ставка без НДС (таблица Kaspi)
    promo_bp: int  # акция 0-0-24, с НДС
    promo_net_bp: int  # акция без НДС — по отношению ставок этой группы (допущение, у Kaspi таблицы нет)


TIERS: dict[str, CommissionTier] = {
    "low": CommissionTier("low", "7,3 %", 730, 640, 770, 675),
    "main": CommissionTier("main", "12,5 % — основная группа", 1250, 1090, 1300, 1134),
    "high": CommissionTier("high", "15,5 %", 1550, 1350, 1610, 1402),
}
DEFAULT_TIER = TIERS["main"]


def tier_for_rate(rate_bp: int) -> CommissionTier | None:
    """Группа по ставке с НДС (обычной или акционной). None — ставка не из таблицы Kaspi."""
    for tier in TIERS.values():
        if rate_bp in (tier.rate_bp, tier.promo_bp):
            return tier
    return None


def net_rate_bp(rate_bp: int) -> int:
    """Ставка без НДС для плательщика НДС: из таблицы Kaspi, иначе — по отношению основной группы (10,9 / 12,5)."""
    for tier in TIERS.values():
        if rate_bp == tier.rate_bp:
            return tier.rate_net_bp
        if rate_bp == tier.promo_bp:
            return tier.promo_net_bp
    return round_half_up_div(rate_bp * DEFAULT_TIER.rate_net_bp, DEFAULT_TIER.rate_bp)


def promo_rate_bp(rate_bp: int) -> int:
    """Акционная ставка 0-0-24 для обычной ставки категории. Ставка не из таблицы — +0,5 п.п. (как в основной группе)."""
    tier = tier_for_rate(rate_bp)
    if tier is not None:
        return tier.promo_bp
    return rate_bp + (DEFAULT_TIER.promo_bp - DEFAULT_TIER.rate_bp)


# --- Доставка (гид q2288, обновлен 16.06.2026), тенге без НДС ---------------------------------------------------

SMALL_ORDER_LIMIT = 10_000  # от 10 000 ₸ — тариф по весу
# (нижняя граница суммы заказа включительно, город, Казахстан/Express)
SMALL_ORDER_TARIFF: tuple[tuple[int, int, int], ...] = (
    (0, 49, 49),
    (1_000, 149, 149),
    (3_000, 199, 199),
    (5_000, 699, 799),
)
# (вес до, кг включительно; город, Казахстан, Express); None — свыше 100 кг
WEIGHT_TARIFF: tuple[tuple[int | None, int, int, int], ...] = (
    (5, 1_099, 1_299, 1_699),
    (15, 1_349, 1_699, 1_849),
    (30, 2_299, 3_599, 3_149),
    (60, 2_899, 5_649, 3_599),
    (100, 4_149, 8_549, 5_599),
    (None, 6_449, 11_999, 8_449),
)
DELIVERY_THRESHOLDS = tuple(t[0] for t in SMALL_ORDER_TARIFF[1:]) + (SMALL_ORDER_LIMIT,)


def delivery_tariff_tenge(order_sum_tenge: int, zone: Zone = "city", weight_kg: float | None = None) -> int:
    """Тариф доставки без НДС по сумме заказа и весу. Шины — отдельные строки тарифа, здесь не считаются."""
    if order_sum_tenge < SMALL_ORDER_LIMIT:
        price = SMALL_ORDER_TARIFF[0]
        for row in SMALL_ORDER_TARIFF:
            if order_sum_tenge >= row[0]:
                price = row
        return price[1] if zone == "city" else price[2]
    col = {"city": 1, "kz": 2, "express": 3}[zone]
    weight = 0.0 if weight_kg is None else weight_kg
    for row in WEIGHT_TARIFF:
        if row[0] is None or weight <= row[0]:
            return row[col]
    raise AssertionError("unreachable")


def with_vat(minor: int) -> int:
    return minor + apply_bp(minor, VAT_BP)


def without_vat(minor_with_vat: int) -> int:
    """Сумма без НДС из суммы с НДС 16 %: x / 1,16 с округлением до тиына."""
    return round_half_up_div(minor_with_vat * 10_000, 10_000 + VAT_BP)


# --- Прибыль единицы товара («прогноз») ----------------------------------------------------------------------------

@dataclass(frozen=True)
class UnitEconomics:
    price_minor: int
    revenue_minor: int  # для плательщика НДС — без НДС
    commission_minor: int
    delivery_minor: int
    cost_minor: int
    tax_minor: int
    profit_minor: int


def unit_profit(price_minor: int, cost_minor: int, rate_bp: int, *, vat_payer: bool = False,
                tax_bp: int | None = None, zone: Zone = "city", weight_kg: float | None = None,
                delivery_tariff_minor: int | None = None) -> UnitEconomics:
    """Прибыль с одной единицы, проданной отдельным заказом.

    Неплательщик НДС: прибыль = цена − комиссия с НДС − доставка с НДС − себестоимость − налог.
    Плательщик НДС: выручка = цена / 1,16; комиссия и доставка — без НДС (НДС к зачёту); налог — с выручки.
    rate_bp — ставка с НДС (как в таблице Kaspi). delivery_tariff_minor — тариф без НДС, если уже известен.
    """
    tariff = (delivery_tariff_minor if delivery_tariff_minor is not None
              else delivery_tariff_tenge(price_minor // 100, zone, weight_kg) * 100)
    if vat_payer:
        revenue = without_vat(price_minor)
        commission = apply_bp(price_minor, net_rate_bp(rate_bp))
        delivery = tariff
    else:
        revenue = price_minor
        commission = apply_bp(price_minor, rate_bp)
        delivery = with_vat(tariff)
    tax = 0 if tax_bp is None else apply_bp(revenue, tax_bp)
    profit = revenue - commission - delivery - cost_minor - tax
    return UnitEconomics(price_minor, revenue, commission, delivery, cost_minor, tax, profit)


def min_price_no_loss(cost_minor: int, rate_bp: int, *, vat_payer: bool = False, tax_bp: int | None = None,
                      zone: Zone = "city", weight_kg: float | None = None) -> int:
    """Минимальная цена в целых тенге (тиыны), при которой прибыль ≥ 0. Учитывает скачки доставки на порогах:
    в каждом диапазоне тарифа решаем линейное неравенство и проверяем, что цена в диапазоне."""
    bounds = [0, *DELIVERY_THRESHOLDS]
    ranges = [(bounds[i], bounds[i + 1] - 1) for i in range(len(bounds) - 1)] + [(SMALL_ORDER_LIMIT, None)]
    for low, high in ranges:
        tariff = delivery_tariff_tenge(low, zone, weight_kg) * 100
        guess = _solve_linear(cost_minor, rate_bp, tariff, vat_payer, tax_bp)
        price_t = max(low, -(-guess // 100))
        # округления по тиынам: поднимаем до первой цены с прибылью ≥ 0
        for _ in range(5):
            if unit_profit(price_t * 100, cost_minor, rate_bp, vat_payer=vat_payer, tax_bp=tax_bp,
                           delivery_tariff_minor=tariff).profit_minor >= 0:
                break
            price_t += 1
        if high is None or price_t <= high:
            return price_t * 100
    raise AssertionError("unreachable")


def _solve_linear(cost: int, rate_bp: int, tariff: int, vat_payer: bool, tax_bp: int | None) -> int:
    """Цена (тиыны) из равенства прибыли нулю без округлений; ответ — с запасом вверх."""
    tax = tax_bp or 0
    if vat_payer:
        # p/1.16·(1 − tax) − p·net − tariff − cost = 0
        k_num = 10_000 * (10_000 - tax) * 10_000 - net_rate_bp(rate_bp) * (10_000 + VAT_BP) * 10_000
        k_den = (10_000 + VAT_BP) * 10_000 * 10_000
        fixed = tariff + cost
    else:
        k_num = 10_000 - rate_bp - tax
        k_den = 10_000
        fixed = with_vat(tariff) + cost
    if k_num <= 0:
        raise ValueError("комиссия и налог не меньше 100 % — безубыточной цены нет")
    return -(-fixed * k_den // k_num)


@dataclass(frozen=True)
class ThresholdHint:
    threshold_tenge: int
    suggested_price_minor: int
    profit_now_minor: int
    profit_suggested_minor: int

    @property
    def gain_minor(self) -> int:
        return self.profit_suggested_minor - self.profit_now_minor


HINT_WINDOW_TENGE = 1_000  # подсказываем, если цена выше порога не больше чем на 1 000 ₸


def threshold_hint(price_minor: int, cost_minor: int, rate_bp: int, *, vat_payer: bool = False,
                   tax_bp: int | None = None, zone: Zone = "city", weight_kg: float | None = None,
                   step_tenge: int = 10) -> ThresholdHint | None:
    """«Цена чуть выше порога доставки»: если цена немного выше порога и цена «порог − 10 ₸» даёт больше прибыли."""
    price_t = price_minor // 100
    for t in DELIVERY_THRESHOLDS:
        if t <= price_t < t + HINT_WINDOW_TENGE:
            suggested = (t - step_tenge) * 100
            now = unit_profit(price_minor, cost_minor, rate_bp, vat_payer=vat_payer, tax_bp=tax_bp,
                              zone=zone, weight_kg=weight_kg).profit_minor
            alt = unit_profit(suggested, cost_minor, rate_bp, vat_payer=vat_payer, tax_bp=tax_bp,
                              zone=zone, weight_kg=weight_kg).profit_minor
            if alt > now:
                return ThresholdHint(t, suggested, now, alt)
    return None


__all__ = [
    "VAT_BP", "TIERS", "DEFAULT_TIER", "CommissionTier", "tier_for_rate", "net_rate_bp", "promo_rate_bp",
    "delivery_tariff_tenge", "with_vat", "without_vat", "UnitEconomics", "unit_profit", "min_price_no_loss",
    "ThresholdHint", "threshold_hint", "DELIVERY_THRESHOLDS", "DELIVERY_FACT_INCLUDES_VAT",
]
