"""Выгрузки (ТЗ 2.1, раздел 9.4 и 9.5): отчёт о прибыли в Excel и «Скачать мои данные».

Все числа считает reports.py; здесь только запись в файлы. Суммы — из тиынов точно (Decimal, без float),
значения, а не формулы. Текст, начинающийся с = + - @, экранируется апострофом (spec 7.6).
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime
from decimal import Decimal
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

from openpyxl import Workbook
from openpyxl.styles import Font
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from .models import (
    AIConversation,
    AITurn,
    CommissionPreset,
    ExpenseEntry,
    Order,
    Product,
    ProductCostVersion,
    Shop,
    TaxRate,
    User,
)
from .periods import Period
from .reports import ItemFact, ShopData, missing_costs, product_stats, profit_breakdown

MONEY_FORMAT = "#,##0.00"
PERCENT_FORMAT = "0.0"
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")
_HEADER_FONT = Font(bold=True)


def _cell(value):
    """Текст, который Excel может принять за формулу, превращаем в обычный текст."""
    if isinstance(value, str) and value.startswith(_FORMULA_PREFIXES):
        return "'" + value
    return value


def _money(minor: int | None):
    """Тиыны → тенге с двумя знаками без float: 123456 → Decimal('1234.56')."""
    return None if minor is None else Decimal(minor).scaleb(-2)


def _sheet(wb: Workbook, title: str, header: list[str], rows: list[list], money_cols: set[int] = frozenset(),
           percent_cols: set[int] = frozenset()):
    ws = wb.create_sheet(title)
    ws.append([_cell(h) for h in header])
    for cell in ws[1]:
        cell.font = _HEADER_FONT
    for row in rows:
        ws.append([_cell(v) for v in row])
    for col in money_cols:
        for cell in ws[f"{_col(col)}"][1:]:
            cell.number_format = MONEY_FORMAT
    for col in percent_cols:
        for cell in ws[f"{_col(col)}"][1:]:
            cell.number_format = PERCENT_FORMAT
    for i, h in enumerate(header, start=1):
        ws.column_dimensions[_col(i - 1)].width = max(12, min(40, len(str(h)) + 4))
    ws.freeze_panes = "A2"
    return ws


def _col(index: int) -> str:
    """Индекс колонки с нуля → буква (0 → A)."""
    letters = ""
    n = index + 1
    while n:
        n, rem = divmod(n - 1, 26)
        letters = chr(65 + rem) + letters
    return letters


def profit_workbook(data: ShopData, facts: list[ItemFact], period: Period, now: datetime) -> bytes:
    """Отчёт о прибыли за период (spec 9.5): «Сводка», «Товары», «Заказы», «Не хватает данных»."""
    wb = Workbook()
    wb.remove(wb.active)

    breakdown = profit_breakdown(data, facts, period)
    summary_rows: list[list] = [
        ["Магазин", data.shop.name],
        ["Период", f"{period.start.isoformat()} – {period.end.isoformat()}"],
        ["Время данных", now.astimezone(data.tz).strftime("%d.%m.%Y %H:%M")],
        [],
        ["Статья", "Сумма, ₸"],
    ]
    for step in breakdown["steps"]:
        summary_rows.append([step["label"], _money(step["minor"])])
    summary_rows += [
        [],
        ["Покрытие данными, %", Decimal(breakdown["coverage_bp"]).scaleb(-2)],
        [breakdown["note"]],
    ]
    ws = wb.create_sheet("Сводка")
    for row in summary_rows:
        ws.append([_cell(v) for v in row])
    for cell in ws[5]:
        cell.font = _HEADER_FONT
    for r in range(6, 6 + len(breakdown["steps"])):
        ws.cell(row=r, column=2).number_format = MONEY_FORMAT
    ws.column_dimensions["A"].width = 44
    ws.column_dimensions["B"].width = 26

    # Товары: те же числа, что на экране товаров
    stats = product_stats(data, facts, period)
    comp = defaultdict(lambda: {"landed": 0, "commission": 0, "delivery": 0, "tax": 0})
    for f in facts:
        if f.is_sale and f.complete and f.sale_day and period.contains(f.sale_day):
            c = comp[f.product_id]
            c["landed"] += f.landed or 0
            c["commission"] += f.commission or 0
            c["delivery"] += f.delivery or 0
            c["tax"] += f.tax
    product_rows = []
    for s in sorted(stats.values(), key=lambda s: s.product.sku):
        if not s.sold_qty and not s.returned_qty:
            continue
        c = comp[s.product.id]
        product_rows.append([
            s.product.sku, s.product.name, s.sold_qty, _money(s.net_sales),
            _money(c["landed"]), _money(c["commission"]), _money(c["delivery"]), _money(c["tax"]),
            _money(s.profit), None if s.margin_bp is None else Decimal(s.margin_bp).scaleb(-2),
            "полные данные" if s.complete else "не хватает данных",
        ])
    _sheet(wb, "Товары",
           ["Артикул", "Название", "Продано, шт", "Чистые продажи, ₸", "Себестоимость, ₸", "Комиссия, ₸",
            "Доставка, ₸", "Налог, ₸", "Прибыль, ₸", "Маржа, %", "Полнота данных"],
           product_rows, money_cols={3, 4, 5, 6, 7, 8}, percent_cols={9})

    # Заказы: строки по дате выдачи, суммы — по полному набору
    by_order: dict[str, dict] = {}
    for f in facts:
        if not (f.is_sale and f.sale_day and period.contains(f.sale_day)):
            continue
        o = by_order.setdefault(f.order_id, {"number": f.order_number, "status": f.status, "day": f.sale_day,
                                             "qty": 0, "gross": 0, "commission": 0, "tax": 0, "profit": 0,
                                             "complete": True})
        o["qty"] += f.qty
        o["gross"] += f.gross
        o["commission"] += f.commission or 0
        o["tax"] += f.tax
        if f.complete:
            o["profit"] += f.sale_profit or 0
        else:
            o["complete"] = False
    order_rows = []
    for o in sorted(by_order.values(), key=lambda o: (o["day"], o["number"])):
        order_rows.append([
            o["number"], o["day"].isoformat(), o["status"], o["qty"], _money(o["gross"]),
            _money(o["commission"]), _money(o["tax"]),
            _money(o["profit"]) if o["complete"] else None,
            "полные данные" if o["complete"] else "не хватает данных",
        ])
    _sheet(wb, "Заказы",
           ["Номер заказа", "Дата выдачи", "Статус", "Товаров, шт", "Сумма, ₸", "Комиссия, ₸", "Налог, ₸",
            "Прибыль, ₸", "Полнота данных"],
           order_rows, money_cols={4, 5, 6, 7})

    missing_rows = [[m["sku"], m["name"], m["category"],
                     "нет закупочной цены"] for m in missing_costs(data)]
    _sheet(wb, "Не хватает данных", ["Артикул", "Название", "Категория", "Причина"], missing_rows)

    out = BytesIO()
    wb.save(out)
    return out.getvalue()


def profit_filename(period: Period) -> str:
    return f"satti-pribyl-{period.start.isoformat()}_{period.end.isoformat()}.xlsx"


def user_shops(db: DbSession, user: User) -> list[Shop]:
    return list(db.scalars(select(Shop).where(Shop.owner_user_id == user.id, Shop.is_demo.is_(False))).all())


def _shop_workbook(db: DbSession, shops: list[Shop]) -> bytes:
    """shop.xlsx: товары, затраты (все версии), заказы, возвраты, комиссии, расходы, налог (spec 9.4)."""
    wb = Workbook()
    wb.remove(wb.active)
    products, costs, orders, returns, commissions, expenses, taxes = [], [], [], [], [], [], []
    for shop in shops:
        pmap = {p.id: p for p in db.scalars(select(Product).where(Product.shop_id == shop.id)).all()}
        for p in pmap.values():
            products.append([shop.name, p.sku, p.name, p.category])
        for v in db.scalars(select(ProductCostVersion).where(ProductCostVersion.shop_id == shop.id)).all():
            p = pmap.get(v.product_id)
            costs.append([shop.name, p.sku if p else "", _money(v.purchase_minor),
                          _money(v.delivery_to_warehouse_minor), _money(v.packaging_minor), _money(v.other_minor),
                          v.effective_from.isoformat() if v.effective_from else "", v.source,
                          "отменена" if v.cancelled else "действует"])
        for o in db.scalars(select(Order).where(Order.shop_id == shop.id)).all():
            for item in o.items:
                p = pmap.get(item.product_id)
                orders.append([shop.name, o.number, o.status, o.created_at.isoformat(),
                               o.completed_at.isoformat() if o.completed_at else "",
                               p.sku if p else "", item.qty, _money(item.unit_price_minor),
                               _money(item.buyer_delivery_minor),
                               None if item.commission_rate_bp is None else Decimal(item.commission_rate_bp).scaleb(-2)])
                for r in item.returns:
                    returns.append([shop.name, o.number, p.sku if p else "", r.returned_qty,
                                    r.confirmed_at.isoformat(), _money(r.refund_minor),
                                    _money(r.commission_returned_minor), _money(r.delivery_returned_minor),
                                    _money(r.reverse_delivery_minor),
                                    "" if r.goods_sellable is None else ("да" if r.goods_sellable else "нет")])
        for c in db.scalars(select(CommissionPreset).where(CommissionPreset.shop_id == shop.id)).all():
            commissions.append([shop.name, c.category, Decimal(c.rate_bp).scaleb(-2),
                                c.effective_from.isoformat() if c.effective_from else "", c.source])
        for e in db.scalars(select(ExpenseEntry).where(ExpenseEntry.shop_id == shop.id)).all():
            expenses.append([shop.name, e.kind, _money(e.amount_minor), e.period_start.isoformat(),
                             e.period_end.isoformat()])
        for t in db.scalars(select(TaxRate).where(TaxRate.shop_id == shop.id)).all():
            taxes.append([shop.name, None if t.rate_bp is None else Decimal(t.rate_bp).scaleb(-2),
                          t.effective_from.isoformat() if t.effective_from else "",
                          t.created_at.isoformat()])

    _sheet(wb, "Товары", ["Магазин", "Артикул", "Название", "Категория"], products)
    _sheet(wb, "Затраты", ["Магазин", "Артикул", "Закупка, ₸", "Доставка на склад, ₸", "Упаковка, ₸", "Прочее, ₸",
                           "Действует с", "Источник", "Статус"],
           costs, money_cols={2, 3, 4, 5})
    _sheet(wb, "Заказы", ["Магазин", "Номер", "Статус", "Создан", "Выдан", "Артикул", "Количество",
                          "Цена, ₸", "Доставка покупателю, ₸", "Ставка комиссии, %"],
           orders, money_cols={7, 8}, percent_cols={9})
    _sheet(wb, "Возвраты", ["Магазин", "Номер", "Артикул", "Количество", "Подтверждён", "Возврат, ₸",
                            "Комиссия возвращена, ₸", "Доставка возвращена, ₸", "Обратная доставка, ₸", "Товар годен"],
           returns, money_cols={5, 6, 7, 8})
    _sheet(wb, "Комиссии", ["Магазин", "Категория", "Ставка, %", "Действует с", "Источник"],
           commissions, percent_cols={2})
    _sheet(wb, "Расходы", ["Магазин", "Вид", "Сумма, ₸", "С", "По"], expenses, money_cols={2})
    _sheet(wb, "Налог", ["Магазин", "Ставка, %", "Действует с", "Записано"], taxes, percent_cols={1})
    out = BytesIO()
    wb.save(out)
    return out.getvalue()


def user_export_zip(db: DbSession, user: User) -> bytes:
    """«Скачать мои данные» (spec 9.4): ZIP с профилем, таблицей магазина, диалогами, согласиями и подпиской."""
    shops = user_shops(db, user)
    profile = {
        "email": user.email,
        "name": user.name,
        "locale": user.locale,
        "created_at": user.created_at.isoformat(),
        "shops": [{"name": s.name, "timezone": s.timezone, "language": s.language,
                   "created_at": s.created_at.isoformat()} for s in shops],
    }
    conversations = []
    for shop in shops:
        for c in db.scalars(select(AIConversation).where(AIConversation.shop_id == shop.id)).all():
            turns = db.scalars(select(AITurn).where(AITurn.conversation_id == c.id).order_by(AITurn.created_at)).all()
            conversations.append({
                "title": c.title,
                "created_at": c.created_at.isoformat(),
                "turns": [{"created_at": t.created_at.isoformat(), "question": t.question,
                           "answer": json.loads(t.answer_json or "{}")} for t in turns],
            })
    consents = {
        "ai": {
            "version": user.ai_consent_version,
            "granted_at": user.ai_consent_at.isoformat() if user.ai_consent_at else None,
            "revoked_at": user.ai_consent_revoked_at.isoformat() if user.ai_consent_revoked_at else None,
        },
    }
    subscription = {"state": "not_available", "note": "Подписка в этой версии не подключена."}

    buf = BytesIO()
    with ZipFile(buf, "w", ZIP_DEFLATED) as z:
        z.writestr("profile.json", json.dumps(profile, ensure_ascii=False, indent=2))
        z.writestr("shop.xlsx", _shop_workbook(db, shops))
        z.writestr("assistant.json", json.dumps({"conversations": conversations}, ensure_ascii=False, indent=2))
        z.writestr("consents.json", json.dumps(consents, ensure_ascii=False, indent=2))
        z.writestr("subscription.json", json.dumps(subscription, ensure_ascii=False, indent=2))
    return buf.getvalue()


__all__ = ["profit_workbook", "profit_filename", "user_export_zip", "user_shops"]
