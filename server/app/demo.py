"""Демо-магазин (docs/spec.md, раздел 9). Выдуманные товары и заказы, без данных покупателей.

generate_demo(db, anchor_date, seed=42) создаёт магазин с 40 товарами D001–D040,
300 заказами за 90 дней и демо-ставками комиссии. Результат детерминирован при фиксированном seed.
"""

from __future__ import annotations

import random
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session as DbSession

from .money import apply_bp
from .models import (
    CommissionPreset,
    ExpenseEntry,
    Order,
    OrderItem,
    Product,
    ProductCostVersion,
    ReturnEvent,
    Shop,
)

TZ = "Asia/Almaty"
CATEGORIES = ["Посуда", "Электроника", "Дом", "Спорт", "Детям", "Красота"]
DEMO_COMMISSION_BP = 1000  # 10%, демо-ставка

# (артикул, название, категория, цена ₸, закупка ₸, доставка до склада ₸, доставка покупателю ₸)
# Закупка None — товар без закупки (D031–D040).
_NAMED: dict[str, tuple] = {
    "D003": ("Набор контейнеров для еды, 5 шт.", "Посуда", 3300, 1900, 150, 300),
    "D007": ("Термокружка 450 мл, нержавейка", "Посуда", 5490, 2800, 300, 500),
    "D008": ("Коврик для йоги 6 мм", "Спорт", 4200, 2200, 200, 400),
    "D012": ("Беспроводные наушники TWS", "Электроника", 7400, 3900, 250, 500),
    "D017": ("Увлажнитель воздуха 2,5 л", "Дом", 15990, 9800, 500, 800),
    "D023": ("Детский рюкзак с подсветкой", "Детям", 1800, 1700, 200, 500),  # продаётся в минус
    "D031": ("Фен-щётка для волос 1200 Вт", "Красота", 9900, None, None, 600),
}

_GENERIC = [
    ("Мини-вентилятор настольный", "Дом"), ("Органайзер для ванной", "Дом"),
    ("Светильник ночной с датчиком", "Дом"), ("Скакалка со счётчиком", "Спорт"),
    ("Гантели неопреновые 2 кг", "Спорт"), ("Бутылка для воды 1 л", "Спорт"),
    ("Пазлы 500 деталей", "Детям"), ("Конструктор 120 деталей", "Детям"),
    ("Расчёска массажная", "Красота"), ("Маска для лица набор", "Красота"),
    ("Power bank 10000 мАч", "Электроника"), ("Зарядка USB-C 20 Вт", "Электроника"),
    ("Чехол для телефона силиконовый", "Электроника"), ("Кружка с термоиндикатором", "Посуда"),
    ("Разделочная доска бамбук", "Посуда"), ("Контейнер для круп 1,5 л", "Посуда"),
    ("Плед флисовый 150х200", "Дом"), ("Аромадиффузор 200 мл", "Дом"),
    ("Коврик для мыши большой", "Электроника"), ("Фонарь налобный", "Спорт"),
    ("Очки для плавания", "Спорт"), ("Игрушка антистресс набор", "Детям"),
    ("Блокнот с ручкой A5", "Детям"), ("Сушилка для овощей", "Дом"),
    ("Набор ножей 5 предметов", "Посуда"), ("Гель для душа 1 л", "Красота"),
    ("Пилка для ногтей электрическая", "Красота"), ("Тонометр автоматический", "Дом"),
    ("Весы кухонные электронные", "Дом"), ("Термос 500 мл", "Посуда"),
    ("Наушники проводные с микрофоном", "Электроника"),
    ("Держатель для телефона на руль", "Электроника"), ("Сумка для йоги", "Спорт"),
]

_STATUS_PLAN = (
    ["completed"] * 220
    + ["returned"] * 12
    + ["partial_return"] * 3
    + ["cancelled"] * 25
    + ["in_progress"] * 20
    + ["pending"] * 20
)


def _catalog() -> list[tuple[str, str, str, int, int | None, int | None, int]]:
    """Список (артикул, название, категория, цена, закупка, доставка до склада, доставка покупателю)."""
    rows = []
    generic = iter(_GENERIC)
    for n in range(1, 41):
        sku = f"D{n:03d}"
        if sku in _NAMED:
            name, cat, price, cost, to_wh, buyer_del = _NAMED[sku]
            rows.append((sku, name, cat, price, cost, to_wh, buyer_del))
            continue
        name, cat = next(generic)
        price = {"Посуда": 2400, "Электроника": 5200, "Дом": 6400, "Спорт": 3100,
                 "Детям": 1900, "Красота": 3800}[cat]
        cost = int(price * 0.55)
        rows.append((sku, name, cat, price, cost, 200, 450))
    return rows


def _no_cost_skus() -> set[str]:
    return {f"D{n:03d}" for n in range(31, 41)}


def _no_sales_skus() -> set[str]:
    return {"D036", "D037", "D038"}


def generate_demo(db: DbSession, anchor_date: date, seed: int = 42, shop: Shop | None = None) -> Shop:
    rng = random.Random(seed)
    tz = ZoneInfo(TZ)
    if shop is None:
        shop = Shop(is_demo=True, name="Демо-магазин", timezone=TZ, language="ru", owner_user_id=None)
        db.add(shop)
        db.flush()

    catalog = _catalog()
    products: dict[str, Product] = {}
    no_cost = _no_cost_skus()
    for sku, name, cat, price, cost, to_wh, _ in catalog:
        p = Product(shop_id=shop.id, sku=sku, name=name, category=cat)
        db.add(p)
        products[sku] = p
    db.flush()

    for cat in CATEGORIES:
        db.add(CommissionPreset(shop_id=shop.id, category=cat, rate_bp=DEMO_COMMISSION_BP,
                                effective_from=None, source="demo", verified=False, demo=True))

    for sku, name, cat, price, cost, to_wh, _ in catalog:
        if cost is None or sku in no_cost:
            continue
        db.add(ProductCostVersion(
            shop_id=shop.id, product_id=products[sku].id, purchase_minor=cost * 100,
            delivery_to_warehouse_minor=(to_wh or 0) * 100, packaging_minor=0, other_minor=0,
            effective_from=None, source="demo",
        ))

    # Заказы: даты за 90 дней до anchor_date (включительно)
    price_by_sku = {c[0]: c for c in catalog}
    skus = [c[0] for c in catalog]
    weights = [0.6 if s in _no_sales_skus() else 1.0 for s in skus]
    recent_start = anchor_date - timedelta(days=13)
    order_seq = 584_100_000 + rng.randint(1000, 9000)

    plan = list(_STATUS_PLAN)
    rng.shuffle(plan)
    return_idx = [i for i, s in enumerate(plan) if s in ("returned", "partial_return")]
    d017_returns = set(return_idx[:9])

    for idx, status in enumerate(plan):
        if status in ("in_progress", "pending"):
            day = anchor_date - timedelta(days=rng.randint(0, 2))
        else:
            day = anchor_date - timedelta(days=rng.randint(3, 89))
        created = datetime.combine(day, time(rng.randint(8, 21), rng.randint(0, 59)), tzinfo=tz)

        completed_at = None
        if status in ("completed", "returned", "partial_return"):
            completed_at = created + timedelta(days=rng.randint(1, 3))
            if completed_at.date() > anchor_date:
                completed_at = datetime.combine(anchor_date, time(12, 0), tzinfo=tz)

        order_seq += rng.randint(1, 37)
        order = Order(shop_id=shop.id, number=str(order_seq), status=status,
                      created_at=created.astimezone(timezone.utc),
                      completed_at=completed_at.astimezone(timezone.utc) if completed_at else None)
        db.add(order)
        db.flush()

        n_items = rng.choices([1, 2, 3], weights=[6, 3, 1])[0]
        chosen: list[str] = []
        for _ in range(n_items):
            offset = (anchor_date - created.date()).days
            sku = _pick_sku(rng, skus, weights, offset=offset, price_by_sku=price_by_sku)
            if sku not in chosen:
                chosen.append(sku)
        is_return = status in ("returned", "partial_return")
        if is_return and idx in d017_returns:
            chosen = ["D017"] + [s for s in chosen if s != "D017"]
        elif is_return:
            chosen = [s if s != "D017" else "D001" for s in chosen]

        for pos, sku in enumerate(chosen):
            _, _, _, price, _, _, buyer_del = price_by_sku[sku]
            qty = rng.choices([1, 2, 3], weights=[7, 2, 1])[0]
            item = OrderItem(
                order_id=order.id, shop_id=shop.id, product_id=products[sku].id, qty=qty,
                unit_price_minor=price * 100,
                buyer_delivery_minor=buyer_del * 100,  # доставка покупателю за строку
                commission_rate_bp=None,  # ставка берётся из пресета категории на дату продажи
            )
            db.add(item)
            db.flush()
            if is_return and pos == 0:  # возврат — по первой позиции заказа: 15 возвратов на 15 заказов
                _add_return(db, item, status, idx, completed_at, anchor_date, rng)

    db.add(ExpenseEntry(shop_id=shop.id, kind="ads", amount_minor=45_000 * 100,
                        period_start=anchor_date - timedelta(days=29), period_end=anchor_date, source="demo"))
    db.add(ExpenseEntry(shop_id=shop.id, kind="other", amount_minor=12_000 * 100,
                        period_start=anchor_date - timedelta(days=59), period_end=anchor_date - timedelta(days=30),
                        source="demo"))
    db.flush()
    return shop


def _pick_sku(rng, skus, weights, offset: int, price_by_sku) -> str:
    """offset — сколько дней назад создан заказ (0 — сегодня).

    Последние 14 дней (offset 0–13): D007 продаётся реже (≈35% от обычного), это падение продаж.
    Предыдущие 14 дней (offset 14–27): D007 продаётся заметно чаще, чтобы падение было видно в сравнении.
    """
    for _ in range(50):
        if 14 <= offset <= 27 and rng.random() < 0.35:
            sku = "D007"
        else:
            sku = rng.choices(skus, weights=weights)[0]
        if sku == "D007" and offset <= 13 and rng.random() > 0.35:
            continue  # падение продаж D007 за последние 14 дней (60–70%)
        if sku in _no_sales_skus():
            continue
        return sku
    return "D001"


def _add_return(db: DbSession, item: OrderItem, status: str, idx: int, completed_at, anchor_date, rng) -> None:
    returned_qty = item.qty if status == "returned" else max(1, item.qty - 1)
    if item.qty == 1 and status == "partial_return":
        returned_qty = 1
    confirmed = completed_at + timedelta(days=rng.randint(3, 8))
    if confirmed.date() > anchor_date:
        confirmed = datetime.combine(anchor_date, time(18, 0), tzinfo=completed_at.tzinfo)
    gross_returned = item.unit_price_minor * returned_qty
    commission_bp = DEMO_COMMISSION_BP
    db.add(ReturnEvent(
        item_id=item.id, shop_id=item.shop_id, returned_qty=returned_qty,
        confirmed_at=confirmed.astimezone(timezone.utc),
        refund_minor=gross_returned,
        commission_returned_minor=apply_bp(gross_returned, commission_bp),
        delivery_returned_minor=0,
        reverse_delivery_minor=0,
        goods_sellable=True,
    ))
    db.flush()
