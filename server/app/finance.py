"""Финансовая модель (docs/spec.md, раздел 6). Все формулы здесь; приложение только показывает.

Продажа (относится к дате выдачи заказа):
  gross_i      = цена × количество
  landed_i     = себестоимость единицы × количество
  commission_i = round_half_up(gross_i × rate_bp / 10000)
  delivery_i   = доставка покупателю (за счёт продавца), на строку
  sale_profit  = gross − landed − commission − delivery

Возврат (относится к дате подтверждения возврата):
  refund        — возврат покупателю (уменьшает чистые продажи)
  profit_delta  = −refund
                  + landed возвращённого товара (если товар годен)
                  + возвращённая комиссия
                  − (обратная доставка − возвращённая доставка)

Если какой-либо компонент неизвестен, прибыль = None (unknown): строка
не входит в «полный набор» и в точный итог прибыли.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Optional

from .money import apply_bp, round_half_up_div


@dataclass(frozen=True)
class Return:
    """Возврат строки. Суммы в тиынах; None — компонент неизвестен."""

    returned_qty: int
    refund_minor: Optional[int]
    commission_returned_minor: Optional[int]
    delivery_returned_minor: Optional[int]
    reverse_delivery_minor: Optional[int]
    goods_sellable: Optional[bool]


@dataclass(frozen=True)
class SaleLine:
    qty: int
    unit_price_minor: int
    status: str  # completed | cancelled | pending | in_progress
    unit_cost_minor: Optional[int]  # полная себестоимость единицы; None — неизвестна
    buyer_delivery_minor: Optional[int]  # доставка покупателю за строку; None — неизвестна
    commission_rate_bp: Optional[int]  # None — ставка неизвестна
    returns: list[Return] = field(default_factory=list)


@dataclass(frozen=True)
class SaleResult:
    gross_minor: int
    landed_minor: Optional[int]
    commission_minor: Optional[int]
    delivery_minor: Optional[int]
    profit_minor: Optional[int]

    @property
    def is_complete(self) -> bool:
        return self.profit_minor is not None


@dataclass(frozen=True)
class LineResult:
    net_sales_minor: int
    profit_minor: Optional[int]
    is_complete: bool


@dataclass(frozen=True)
class Totals:
    orders_minor: int
    completed_gross_minor: int
    returns_minor: int
    cancelled_minor: int
    net_sales_all_minor: int
    net_sales_complete_minor: int
    profit_minor: int
    coverage_bp: int
    margin_bp: int


def return_is_known(ret: Return) -> bool:
    return None not in (
        ret.refund_minor,
        ret.commission_returned_minor,
        ret.delivery_returned_minor,
        ret.reverse_delivery_minor,
        ret.goods_sellable,
    )


def sale_result(line: SaleLine) -> SaleResult:
    """Прибыль самой продажи, без возвратов."""
    gross = line.unit_price_minor * line.qty
    landed = None if line.unit_cost_minor is None else line.unit_cost_minor * line.qty
    commission = None if line.commission_rate_bp is None else apply_bp(gross, line.commission_rate_bp)
    delivery = line.buyer_delivery_minor
    profit = None
    if None not in (landed, commission, delivery):
        profit = gross - landed - commission - delivery
    return SaleResult(gross, landed, commission, delivery, profit)


def return_profit_delta(line: SaleLine, ret: Return) -> Optional[int]:
    """Изменение прибыли из-за одного возврата. None — неизвестно."""
    if not return_is_known(ret):
        return None
    recovered = 0
    if ret.goods_sellable:
        if line.unit_cost_minor is None:
            return None
        recovered = line.unit_cost_minor * ret.returned_qty
    extra_delivery = ret.reverse_delivery_minor - ret.delivery_returned_minor
    return -ret.refund_minor + recovered + ret.commission_returned_minor - extra_delivery


def calc_line(line: SaleLine) -> LineResult:
    """Итог по строке за всё время: продажа плюс все её возвраты."""
    if line.status == "cancelled":
        return LineResult(net_sales_minor=0, profit_minor=0, is_complete=True)
    if line.status != "completed":
        return LineResult(net_sales_minor=0, profit_minor=None, is_complete=False)

    sale = sale_result(line)
    net = sale.gross_minor
    profit = sale.profit_minor
    complete = sale.is_complete
    for ret in line.returns:
        if return_is_known(ret):
            net -= ret.refund_minor
        else:
            complete = False
        delta = return_profit_delta(line, ret)
        if delta is None:
            complete = False
        elif profit is not None:
            profit += delta
    if not complete:
        profit = None
    return LineResult(net_sales_minor=net, profit_minor=profit, is_complete=complete)


def calc_totals(lines: list[SaleLine]) -> Totals:
    from .money import round_half_up_div as rhu

    orders = completed_gross = returns = cancelled = 0
    net_all = net_complete = profit_total = 0
    for line in lines:
        order_sum = line.unit_price_minor * line.qty
        orders += order_sum
        if line.status == "cancelled":
            cancelled += order_sum
            continue
        if line.status != "completed":
            continue
        res = calc_line(line)
        completed_gross += order_sum
        returns += sum(r.refund_minor or 0 for r in line.returns)
        net_all += res.net_sales_minor
        if res.is_complete:
            net_complete += res.net_sales_minor
            profit_total += res.profit_minor

    coverage = rhu(net_complete * 10_000, net_all) if net_all else 0
    margin = rhu(profit_total * 10_000, net_complete) if net_complete else 0
    return Totals(
        orders_minor=orders,
        completed_gross_minor=completed_gross,
        returns_minor=returns,
        cancelled_minor=cancelled,
        net_sales_all_minor=net_all,
        net_sales_complete_minor=net_complete,
        profit_minor=profit_total,
        coverage_bp=coverage,
        margin_bp=margin,
    )


__all__ = [
    "Return",
    "SaleLine",
    "SaleResult",
    "LineResult",
    "Totals",
    "sale_result",
    "return_profit_delta",
    "return_is_known",
    "calc_line",
    "calc_totals",
    "replace",
    "round_half_up_div",
]
