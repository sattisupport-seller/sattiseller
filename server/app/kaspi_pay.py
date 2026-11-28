"""Сверка с Kaspi (К-33, Б1): выгрузка Kaspi Pay → «Продажи» (Excel, гид q2292) против расчёта Satti.

Каркас на синтетическом файле. Колонки узнаём по подсказкам в заголовках; точные названия — по реальному файлу
продавца (он лежит вне папки проекта, в Git не кладём). Если нужная колонка не найдена — понятная ошибка
со списком заголовков файла, чтобы подстроить подсказки за минуту.

Сверка по каждому заказу, до тенге (допуск — меньше 1 ₸ на округление):
- сумма продажи — цена × количество по позициям Satti;
- комиссия Kaspi — с НДС (так Kaspi удерживает): по ставке позиции;
- доставка продавца — сумма, которую Satti хранит (с НДС).
Возвраты в выгрузке — отрицательные суммы: складываются со своим заказом (сверяется итог по заказу).
Строки сохраняются (kaspi_pay_rows) — после проверки формата на реальном файле факт Kaspi пойдёт в прибыль.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy import delete, select
from sqlalchemy.orm import Session as DbSession

from .errors import ApiError
from .imports import ParsedFile
from .models import KaspiPayRow, Shop
from .money import apply_bp
from .reports import SALE_STATUSES, base_for

TOLERANCE_MINOR = 99  # меньше 1 ₸ — округление, не расхождение

# подсказки заголовков (в нижнем регистре, по вхождению); порядок важен — первая подходящая колонка
HINTS: dict[str, list[str]] = {
    "order": ["номер заказа", "№ заказа", "n заказа", "заказ №", "номер покупки", "order"],
    "payout": ["к выплате", "к перечислению", "к зачислению", "сумма зачисления", "зачислено"],
    "commission": ["комиссия", "удержано за приём оплаты", "удержано за прием оплаты", "за приём оплаты"],
    "delivery": ["доставка", "стоимость доставки"],
    "amount": ["сумма заказа", "сумма покупки", "сумма продажи", "сумма операции", "сумма"],
}
REQUIRED = ("order", "amount")
FIELD_TITLES = {"order": "номер заказа", "amount": "сумма", "commission": "комиссия", "delivery": "доставка",
                "payout": "к выплате"}


def find_columns(columns: list[str]) -> dict[str, int]:
    """Индекс колонки для каждого поля по подсказкам. Колонка не используется дважды."""
    low = [str(c or "").strip().lower() for c in columns]
    used: set[int] = set()
    out: dict[str, int] = {}
    for key, hints in HINTS.items():
        for hint in hints:
            idx = next((i for i, c in enumerate(low) if i not in used and hint in c), None)
            if idx is not None:
                out[key] = idx
                used.add(idx)
                break
    missing = [FIELD_TITLES[k] for k in REQUIRED if k not in out]
    if missing:
        found = ", ".join(f"«{c}»" for c in columns if str(c or "").strip()) or "нет заголовков"
        raise ApiError(422, "kaspi_pay_columns",
                       f"Не нашли колонки: {', '.join(missing)}. Заголовки в файле: {found}. "
                       "Выгрузите отчёт «Продажи» из Kaspi Pay (веб-версия) в Excel без изменений.")
    return out


_MONEY_JUNK = re.compile(r"[\s  ₸тгТГ]")


def money_minor(value) -> int | None:
    """Сумма из ячейки в тиынах: числа, «12 345,50 ₸», «−1 000», «(1 000)». Пусто — None."""
    if value is None:
        return None
    if isinstance(value, (int, float, Decimal)) and not isinstance(value, bool):
        dec = Decimal(str(value))
    else:
        text = _MONEY_JUNK.sub("", str(value)).replace("−", "-").replace("–", "-")
        if not text:
            return None
        negative = text.startswith("(") and text.endswith(")")
        text = text.strip("()").replace(",", ".")
        try:
            dec = Decimal(text)
        except InvalidOperation as exc:
            raise ValueError(f"не сумма: {value!r}") from exc
        if negative:
            dec = -dec
    return int((dec * 100).to_integral_value())


def _order_code(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    code = str(value).strip()
    return code or None


@dataclass
class PayOrder:
    number: str
    amount: int = 0
    commission: int | None = None
    delivery: int | None = None
    payout: int | None = None


@dataclass
class ParsedPay:
    orders: dict[str, PayOrder]
    rows: int
    bad_rows: list[int] = field(default_factory=list)
    columns: dict[str, str] = field(default_factory=dict)


def parse_pay(parsed: ParsedFile) -> ParsedPay:
    cols = find_columns(parsed.columns)
    orders: dict[str, PayOrder] = {}
    bad: list[int] = []
    for row in parsed.rows:
        cells = row.cells
        def cell(key):  # noqa: E306
            i = cols.get(key)
            return cells[i] if i is not None and i < len(cells) else None
        number = _order_code(cell("order"))
        try:
            amount = money_minor(cell("amount"))
            extra = {k: money_minor(cell(k)) for k in ("commission", "delivery", "payout")}
        except ValueError:
            bad.append(row.number)
            continue
        if number is None or amount is None:
            bad.append(row.number)
            continue
        po = orders.setdefault(number, PayOrder(number))
        po.amount += amount
        for k, v in extra.items():
            if v is not None:
                setattr(po, k, (getattr(po, k) or 0) + abs(v))  # удержания в выгрузке бывают со знаком минус
    return ParsedPay(orders, len(parsed.rows), bad, {k: parsed.columns[i] for k, i in cols.items()})


def _ours(db: DbSession, shop: Shop) -> dict[str, dict[str, int | None]]:
    """По номеру заказа: сумма продажи, комиссия с НДС, доставка продавца — из данных Satti."""
    data, facts = base_for(db, shop)
    rate_by_item: dict[tuple[str, str], int | None] = {}
    for f in facts:
        rate_by_item[(f.order_id, f.product_id)] = f.rate_bp
    out: dict[str, dict[str, int | None]] = {}
    for o in data.orders:
        if o.status not in SALE_STATUSES:
            continue
        amount = commission = delivery = 0
        commission_known = True
        for it in o.items:
            gross = it.unit_price_minor * it.qty
            amount += gross
            rate = rate_by_item.get((o.id, it.product_id))
            if rate is None:
                commission_known = False
            else:
                commission += apply_bp(gross, rate)  # ставка позиции — с НДС, как удерживает Kaspi
            delivery += it.buyer_delivery_minor or 0
        out[o.number] = {"amount": amount, "commission": commission if commission_known else None,
                         "delivery": delivery}
    return out


def reconcile(db: DbSession, shop: Shop, pay: ParsedPay, now: datetime) -> dict:
    ours = _ours(db, shop)
    mismatches: list[dict] = []
    matched = 0
    missing: list[str] = []
    diff_orders: set[str] = set()
    diff_sum = 0
    for number, po in sorted(pay.orders.items()):
        mine = ours.get(number)
        if mine is None:
            missing.append(number)
            continue
        ok = True
        for fld, theirs in (("amount", po.amount), ("commission", po.commission), ("delivery", po.delivery)):
            if theirs is None or mine.get(fld) is None:
                continue  # колонки нет в файле или ставка не задана — не сверяем
            diff = theirs - mine[fld]
            if abs(diff) > TOLERANCE_MINOR:
                ok = False
                mismatches.append({"order_number": number, "field": fld, "satti_minor": mine[fld],
                                   "kaspi_minor": theirs, "diff_minor": diff})
                diff_sum += abs(diff)
        if ok:
            matched += 1
        else:
            diff_orders.add(number)

    # сохраняем строки выгрузки (повторная загрузка заказа заменяет его строку)
    numbers = list(pay.orders)
    if numbers:
        db.execute(delete(KaspiPayRow).where(KaspiPayRow.shop_id == shop.id, KaspiPayRow.order_number.in_(numbers)))
        for po in pay.orders.values():
            db.add(KaspiPayRow(shop_id=shop.id, order_number=po.number[:32], amount_minor=po.amount,
                               commission_minor=po.commission, delivery_minor=po.delivery, payout_minor=po.payout,
                               imported_at=now))
        db.commit()

    return {
        "rows": pay.rows,
        "bad_rows": pay.bad_rows[:50],
        "columns": pay.columns,
        "orders_in_file": len(pay.orders),
        "matched": matched,
        "mismatch_orders": len(diff_orders),
        "mismatch_sum_minor": diff_sum,  # «расхождение N ₸ по M заказам»
        "mismatches": mismatches[:200],
        "missing_in_satti": missing[:200],
        "missing_in_satti_count": len(missing),
    }


def stored_count(db: DbSession, shop_id: str) -> int:
    return len(db.scalars(select(KaspiPayRow.id).where(KaspiPayRow.shop_id == shop_id)).all())


__all__ = ["parse_pay", "reconcile", "find_columns", "money_minor", "HINTS", "TOLERANCE_MINOR", "stored_count"]
