"""Финансовая модель (docs/spec.md, раздел 6). Все формулы живут здесь; приложение только показывает.

Прибыль строки (тиыны):
  revenue_i     = цена × количество − возврат покупателю
  landed_cost_i = себестоимость × количество − себестоимость возвращённого (если товар годен)
  commission_i  = round_half_up(цена × количество × rate_bp / 10000) − возвращённая комиссия
  delivery_i    = доставка покупателю + обратная доставка − возвращённая доставка
  profit_i      = revenue_i − landed_cost_i − commission_i − delivery_i

Если какой-то компонент неизвестен, прибыль строки = None (unknown) и строка
выпадает из точного итога (complete_set).
"""

from __future__ import annotations

from dataclasses import dataclass, field
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
    unit_cost_minor: Optional[int]
    buyer_delivery_minor: Optional[int]  # доставка покупателю за счёт продавца, на всю строку
    commission_rate_bp: int
    returns: list[Return] = field(default_factory=list)


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


def _return_is_known(ret: Return) -> bool:
    return None not in (
        ret.refund_minor,
        ret.commission_returned_minor,
        ret.delivery_returned_minor,
        ret.reverse_delivery_minor,
        ret.goods_sellable,
    )


def calc_line(line: SaleLine) -> LineResult:
    if line.status == "cancelled":
        return LineResult(net_sales_minor=0, profit_minor=0, is_complete=True)
    if line.status != "completed":
        # pending / in_progress: только в «Сумме заказов», в прибыль не входят
        return LineResult(net_sales_minor=0, profit_minor=None, is_complete=False)

    order_sum = line.unit_price_minor * line.qty
    revenue = order_sum
    landed_cost: Optional[int] = (
        None if line.unit_cost_minor is None else line.unit_cost_minor * line.qty
    )
    delivery: Optional[int] = line.buyer_delivery_minor
    commission_adj = 0
    is_complete = landed_cost is not None and delivery is not None

    for ret in line.returns:
        if not _return_is_known(ret):
            is_complete = False
            continue
        revenue -= ret.refund_minor
        commission_adj -= ret.commission_returned_minor
        if delivery is not None:
            delivery = delivery + ret.reverse_delivery_minor - ret.delivery_returned_minor
        if landed_cost is not None and ret.goods_sellable:
            landed_cost -= line.unit_cost_minor * ret.returned_qty

    commission = apply_bp(order_sum, line.commission_rate_bp) + commission_adj

    profit: Optional[int] = None
    if is_complete and landed_cost is not None and delivery is not None:
        profit = revenue - landed_cost - commission - delivery
    else:
        is_complete = False

    return LineResult(net_sales_minor=revenue, profit_minor=profit, is_complete=is_complete)


def calc_totals(lines: list[SaleLine]) -> Totals:
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
        if res.is_complete and res.profit_minor is not None:
            net_complete += res.net_sales_minor
            profit_total += res.profit_minor

    coverage = round_half_up_div(net_complete * 10_000, net_all) if net_all else 0
    margin = round_half_up_div(profit_total * 10_000, net_complete) if net_complete else 0

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
