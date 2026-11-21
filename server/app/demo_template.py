"""Демо-магазин из шаблона (1.16, ADR-0005).

Раньше каждая новая демо-установка генерировала все строки заново на Python (сотни объектов и тысячи INSERT).
Теперь есть один шаблон — магазин, сгенерированный generate_demo с фиксированной датой TEMPLATE_ANCHOR.
Новый демо-магазин копируется из шаблона семью запросами INSERT ... SELECT: идентификаторы строк
пересчитываются (md5 исходного id и магазина), даты сдвигаются на разницу между сегодня и TEMPLATE_ANCHOR.
Сдвиг дат на целое число дней даёт те же данные, что генерация на сегодня (проверено тестом test_demo_template.py).
"""

from __future__ import annotations

import re

from datetime import date

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DbSession

from .demo import TZ, generate_demo
from .models import Shop

TEMPLATE_SHOP_ID = "5e3d0000000000000000000000000001"  # служебный магазин-шаблон; не привязан ни к одной установке
TEMPLATE_ANCHOR = date(2026, 1, 1)  # дата, относительно которой сгенерирован шаблон


def ensure_template(db: DbSession) -> None:
    """Создаёт шаблон при первом обращении. Вызывать в начале запроса, до других записей.

    Параллельные запросы при первом создании конкурируют за первичный ключ: проигравший откатывается
    (его транзакция пуста) и далее копирует уже созданный шаблон.
    """
    if db.get(Shop, TEMPLATE_SHOP_ID) is not None:
        return
    try:
        shop = Shop(id=TEMPLATE_SHOP_ID, is_demo=True, name="Шаблон демо-магазина", timezone=TZ, language="ru",
                    owner_user_id=None)
        db.add(shop)
        generate_demo(db, TEMPLATE_ANCHOR, shop=shop)
        db.commit()
    except IntegrityError:
        db.rollback()


def create_demo_from_template(db: DbSession, today: date) -> Shop:
    ensure_template(db)
    shop = Shop(is_demo=True, name="Демо-магазин", timezone=TZ, language="ru", owner_user_id=None)
    db.add(shop)
    db.flush()
    copy_template(db, shop.id, today)
    return shop


def copy_template(db: DbSession, shop_id: str, today: date) -> None:
    """Копирует шаблон в магазин shop_id. Магазин должен быть пуст (после создания или wipe_shop_content)."""
    delta = (today - TEMPLATE_ANCHOR).days
    params = {"shop": shop_id, "tpl": TEMPLATE_SHOP_ID, "delta": delta}
    for sql in _copy_statements(_dialect(db)):
        db.execute(text(sql), params)
    db.flush()


def _dialect(db: DbSession) -> str:
    return db.get_bind().dialect.name


def _newid(dialect: str, col: str) -> str:
    if dialect == "sqlite":
        return f"satti_newid({col}, :shop)"
    return f"md5({col} || :shop)"


def _ts(dialect: str, col: str) -> str:
    if dialect == "sqlite":
        return f"satti_shift_ts({col}, :delta)"
    return f"({col} + make_interval(days => :delta))"


def _now(dialect: str) -> str:
    # created_at версии затрат — момент копирования (как при генерации), а не дата шаблона:
    # иначе защита от повторной отправки (QA-06) видит «будущие» версии
    return "CURRENT_TIMESTAMP" if dialect == "sqlite" else "now()"


def _day(dialect: str, col: str) -> str:
    if dialect == "sqlite":
        return f"satti_shift_date({col}, :delta)"
    return f"CAST({col} + make_interval(days => :delta) AS date)"


# SQL-шаблоны без подстановки в строку Python (значения — только параметрами :shop, :tpl, :delta).
# Вставляемые выражения — N(колонка) новый id, TS(колонка) сдвиг времени, DAY(колонка) сдвиг даты, NOW() момент копирования.
_TEMPLATES = [
    """INSERT INTO products (id, shop_id, sku, name, category)
       SELECT N(p.id), :shop, p.sku, p.name, p.category
       FROM products p WHERE p.shop_id = :tpl""",
    """INSERT INTO commission_presets (id, shop_id, category, rate_bp, effective_from, source, verified, demo)
       SELECT N(c.id), :shop, c.category, c.rate_bp, DAY(c.effective_from), c.source, c.verified, c.demo
       FROM commission_presets c WHERE c.shop_id = :tpl""",
    """INSERT INTO product_cost_versions (id, shop_id, product_id, purchase_minor, delivery_to_warehouse_minor,
           packaging_minor, other_minor, effective_from, source, import_batch_id, cancelled, created_at)
       SELECT N(v.id), :shop, N(v.product_id), v.purchase_minor, v.delivery_to_warehouse_minor,
           v.packaging_minor, v.other_minor, DAY(v.effective_from), v.source, v.import_batch_id,
           v.cancelled, NOW()
       FROM product_cost_versions v WHERE v.shop_id = :tpl""",
    """INSERT INTO orders (id, shop_id, number, status, created_at, completed_at)
       SELECT N(o.id), :shop, o.number, o.status, TS(o.created_at), TS(o.completed_at)
       FROM orders o WHERE o.shop_id = :tpl""",
    """INSERT INTO order_items (id, order_id, shop_id, product_id, qty, unit_price_minor, buyer_delivery_minor,
           commission_rate_bp)
       SELECT N(i.id), N(i.order_id), :shop, N(i.product_id), i.qty, i.unit_price_minor,
           i.buyer_delivery_minor, i.commission_rate_bp
       FROM order_items i WHERE i.shop_id = :tpl""",
    """INSERT INTO return_events (id, item_id, shop_id, returned_qty, confirmed_at, refund_minor,
           commission_returned_minor, delivery_returned_minor, reverse_delivery_minor, goods_sellable)
       SELECT N(r.id), N(r.item_id), :shop, r.returned_qty, TS(r.confirmed_at), r.refund_minor,
           r.commission_returned_minor, r.delivery_returned_minor, r.reverse_delivery_minor, r.goods_sellable
       FROM return_events r WHERE r.shop_id = :tpl""",
    """INSERT INTO expense_entries (id, shop_id, kind, amount_minor, period_start, period_end, source)
       SELECT N(e.id), :shop, e.kind, e.amount_minor, DAY(e.period_start), DAY(e.period_end), e.source
       FROM expense_entries e WHERE e.shop_id = :tpl""",
]

_TOKEN = re.compile(r'\b(N|TS|DAY)\(([A-Za-z_.]+)\)|\bNOW\(\)')


def _copy_statements(dialect: str) -> list[str]:
    """Порядок важен: сначала строки, на которые ссылаются внешние ключи. Выражения подставляются по диалекту."""
    def expand(match: re.Match) -> str:
        if match.group(0) == "NOW()":
            return _now(dialect)
        kind, col = match.group(1), match.group(2)
        builder = {"N": _newid, "TS": _ts, "DAY": _day}[kind]
        return builder(dialect, col)

    return [_TOKEN.sub(expand, sql) for sql in _TEMPLATES]
