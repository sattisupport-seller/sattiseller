"""Главный экран «языком денег» (К-33, А5). Вся арифметика — здесь и в kaspi_tariffs/finance; приложение показывает.

- Утечки маржи: товары в минусе или около нуля за 30 дней (после комиссии с НДС, рассрочки и доставки) —
  убыточные сверху, с разбивкой на единицу и итогом «за месяц вы теряете N ₸ на M товарах».
- Минимальная цена без убытка — по худшей ставке (акция 0-0-24: повышенную комиссию нельзя переложить на
  покупателя, правило Kaspi 3.5), с доставкой по порогам Kaspi и налогом.
- Подсказка «цена чуть выше порога доставки».
- Защита от отмен: товары, которые сейчас сняты с продажи (или сняли бы — в режиме презентации), и доля отмен
  против порога Kaspi 3 %. Слово «штраф» не используем: денежного штрафа в правилах Kaspi нет.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session as DbSession

from .kaspi_tariffs import (DEFAULT_TIER, min_price_no_loss, promo_rate_bp, threshold_hint, unit_profit,
                            without_vat)
from .money import round_half_up_div
from .periods import resolve
from .reports import (SALE_STATUSES, ItemFact, ShopData, local_day, product_stats, rate_on, tax_rate_bp_on,
                      unit_cost_on)

LEAK_MARGIN_BP = 300  # «около нуля»: маржа не больше 3 %
CANCEL_LIMIT_BP = 300  # порог Kaspi: отмены по вине продавца — меньше 3 %
MAX_LEAKS = 20
MAX_HINTS = 10


def _rate_for(data: ShopData, category: str, day) -> int:
    preset = rate_on(data.presets.get(category, []), day)
    return preset.rate_bp if preset else DEFAULT_TIER.rate_bp


def _per_unit(facts: list[ItemFact], pid: str, period) -> dict[str, int]:
    qty = commission = delivery = 0
    for f in facts:
        if (f.product_id == pid and f.is_sale and f.complete and f.sale_day is not None
                and period.start <= f.sale_day <= period.end):
            qty += f.qty
            commission += f.commission or 0
            delivery += f.delivery or 0
    if qty == 0:
        return {"commission": 0, "delivery": 0}
    return {"commission": round_half_up_div(commission, qty), "delivery": round_half_up_div(delivery, qty)}


def _min_price_fixed_delivery(cost: int, rate_bp: int, delivery_net: int, vat_payer: bool, tax_bp: int | None) -> int:
    """Минимальная цена (целые тенге) при известной доставке на единицу (без НДС): прибыль ≥ 0."""
    price_t = 1
    lo, hi = 1, 100_000_000
    while lo < hi:  # прибыль монотонно растёт с ценой — двоичный поиск по целым тенге
        mid = (lo + hi) // 2
        if unit_profit(mid * 100, cost, rate_bp, vat_payer=vat_payer, tax_bp=tax_bp,
                       delivery_tariff_minor=delivery_net).profit_minor >= 0:
            hi = mid
        else:
            lo = mid + 1
    price_t = lo
    return price_t * 100


def money_insights(db: DbSession, data: ShopData, facts: list[ItemFact], now: datetime) -> dict:
    from .stock import stock_states

    shop = data.shop
    period = resolve("30d", shop.timezone, now)
    today = period.end
    vat_payer = bool(getattr(shop, "vat_payer", False))
    tax_bp = tax_rate_bp_on(data.tax_rates, today)
    stats = product_stats(data, facts, period)

    leaks, hints = [], []
    for pid, s in stats.items():
        unit_cost = unit_cost_on(data.versions.get(pid, []), today)
        if unit_cost is None or s.sold_qty <= 0 or s.net_sales <= 0:
            continue
        price = round_half_up_div(s.net_sales, s.sold_qty) if not vat_payer else None
        if price is None:  # плательщик НДС: net_sales без НДС — цену берём из фактов (с НДС)
            gross = sum(f.unit_price * f.qty for f in facts if f.product_id == pid and f.is_sale
                        and f.sale_day is not None and period.start <= f.sale_day <= period.end)
            price = round_half_up_div(gross, s.sold_qty)
        rate = _rate_for(data, s.product.category, today)
        worst = promo_rate_bp(rate)
        per_unit = _per_unit(facts, pid, period)
        if per_unit["delivery"] > 0:
            # фактическая доставка на единицу из заказов (неплательщик — с НДС, плательщик — без) точнее тарифа
            fact_net = per_unit["delivery"] if vat_payer else without_vat(per_unit["delivery"])
            min_price = _min_price_fixed_delivery(unit_cost, worst, fact_net, vat_payer, tax_bp)
            worst_unit = unit_profit(price, unit_cost, worst, vat_payer=vat_payer, tax_bp=tax_bp,
                                     delivery_tariff_minor=fact_net)
        else:  # доставку продавец не платил — прогноз по тарифу Kaspi и порогам суммы заказа
            min_price = min_price_no_loss(unit_cost, worst, vat_payer=vat_payer, tax_bp=tax_bp)
            worst_unit = unit_profit(price, unit_cost, worst, vat_payer=vat_payer, tax_bp=tax_bp)
        row = {"product_id": pid, "sku": s.product.sku, "name": s.product.name, "sold_qty": s.sold_qty,
               "avg_price_minor": price, "unit_cost_minor": unit_cost,
               "profit_minor": s.profit, "margin_bp": s.margin_bp,
               "per_unit": per_unit,
               "worst_rate_bp": worst, "worst_unit_profit_minor": worst_unit.profit_minor,
               "min_price_minor": min_price}
        if s.profit is not None and (s.profit < 0 or (s.margin_bp is not None and s.margin_bp <= LEAK_MARGIN_BP)):
            leaks.append(row)
        hint = threshold_hint(price, unit_cost, rate, vat_payer=vat_payer, tax_bp=tax_bp)
        if hint is not None:
            hints.append({"product_id": pid, "name": s.product.name, "price_minor": price,
                          "threshold_tenge": hint.threshold_tenge, "suggested_price_minor": hint.suggested_price_minor,
                          "gain_per_order_minor": hint.gain_minor})
    leaks.sort(key=lambda r: (r["profit_minor"], r["margin_bp"] if r["margin_bp"] is not None else 0))
    losing = [r for r in leaks if r["profit_minor"] < 0]
    hints.sort(key=lambda h: -h["gain_per_order_minor"])

    # защита от отмен
    orders = [o for o in data.orders if period.start <= local_day(o.created_at, data.tz) <= period.end]
    cancelled = sum(1 for o in orders if o.status == "cancelled")
    share = round_half_up_div(cancelled * 10_000, len(orders)) if orders else 0
    states = stock_states(db, shop, now)
    protected = sorted((st for st in states.values() if st.delisted or st.for_sale <= 0), key=lambda st: st.name)
    sold_orders = sum(1 for o in orders if o.status in SALE_STATUSES)

    return {
        "period": {"from": period.start.isoformat(), "to": period.end.isoformat()},
        "vat_payer": vat_payer,
        "leaks": {
            "items": leaks[:MAX_LEAKS],
            "count": len(leaks),
            "losing_count": len(losing),
            "month_loss_minor": -sum(r["profit_minor"] for r in losing),  # «за месяц вы теряете N ₸»
            "near_zero_bp": LEAK_MARGIN_BP,
        },
        "threshold_hints": hints[:MAX_HINTS],
        "cancel_protection": {
            "protected_count": len(protected),
            "protected": [{"product_id": st.product_id, "name": st.name, "current": st.current} for st in protected[:10]],
            "preview": bool(getattr(shop, "presentation_mode", False)),
            "orders_count": len(orders),
            "sold_orders_count": sold_orders,
            "cancelled_count": cancelled,
            "cancel_share_bp": share,
            "kaspi_limit_bp": CANCEL_LIMIT_BP,
            "note": "Здесь все отмены, включая отмены покупателем: причину отмены Kaspi в заказе не передаёт. "
                    "Kaspi считает только отмены по вине продавца (например, «нет в наличии»); ваш показатель — "
                    "в кабинете Kaspi. "
                    "Порог Kaspi — меньше 3 %, иначе ограничения вплоть до отключения.",
        },
        "time_saving": {"ai_card": True, "reply_templates": True},
    }
