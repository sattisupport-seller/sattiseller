"""Подключение магазина Kaspi: токен, синхронизация заказов, XML-прайс (этап 2, задачи 2.2–2.4).

- Токен хранится только зашифрованным (Fernet, ключ SATTI_KASPI_KEY). В ответах API и журнале его нет.
- Синхронизация идемпотентна: заказ с тем же номером обновляется, а не дублируется. Курсор (время самого свежего
  обработанного заказа) сохраняется после каждой страницы, поэтому сбой не теряет уже обработанное.
- Прайс-лист отдаётся по адресу с секретом (price_key), который меняется при каждом подключении.
"""

from __future__ import annotations

import re
import base64
import hashlib
import logging
import secrets
import threading
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from . import reportcache
from .config import settings
from .kaspi_client import PAGE_SIZE, KaspiAuthError, KaspiClient, KaspiOrder, KaspiUnavailable
from .models import KaspiCatalog, KaspiConnection, Order, OrderItem, Product, Shop, _uid

log = logging.getLogger("satti.kaspi")

# Состояния Kaspi -> статусы заказов Satti. UNVERIFIED: сверить с официальным списком состояний.
STATE_MAP = {
    "NEW": "pending",
    "ACCEPTED_BY_MERCHANT": "in_progress",
    "COMPLETED": "completed",
    "DELIVERED": "completed",
    "CANCELLED": "cancelled",
    "CANCELED": "cancelled",
    "RETURNED": "returned",
}
DEFAULT_STATUS = "in_progress"
FIRST_SYNC_DAYS = 90  # ТЗ: при подключении — заказы за 90 дней
FIRST_STAGE_DAYS = 7  # К-18.3: сначала последние 7 дней (продавец сразу видит данные), остальное — в фоне
# Повторно читаем заказы за 14 дней до курсора: Kaspi меняет состояние заказа позже (возврат, отмена).
OVERLAP_MS = 14 * 86_400_000
UNKNOWN_CATEGORY = "Без категории"


# ---------- шифрование токена ----------

def _fernet():
    """Ключ шифрования токенов (Kaspi и refresh-токены Apple). SATTI_KASPI_KEY может содержать несколько ключей
    через запятую (аудит 27.11, L5: ротация): первый шифрует, все расшифровывают."""
    from cryptography.fernet import MultiFernet

    keys = [k.strip() for k in settings.kaspi_key.split(",") if k.strip()] if settings.kaspi_key else []
    if keys:
        return MultiFernet([Fernet(k.encode()) for k in keys])
    # без ключа (разработка и тесты) — ключ, выведенный из секрета разработки; в продакшене проверка не даст запуститься
    digest = hashlib.sha256(f"kaspi-dev:{settings.admin_totp_key}".encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_token(token: str) -> str:
    return _fernet().encrypt(token.encode()).decode()


def decrypt_token(token_enc: str) -> str:
    try:
        return _fernet().decrypt(token_enc.encode()).decode()
    except InvalidToken as exc:
        raise KaspiAuthError("токен нельзя расшифровать: проверьте SATTI_KASPI_KEY") from exc


# ---------- подключение ----------

def _now_ms(now: datetime) -> int:
    return int(now.timestamp() * 1000)


def _utc(ms: int) -> datetime:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc)


def _aware(dt: datetime) -> datetime:
    """Время из базы может прийти без часового пояса (SQLite): считаем его UTC."""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def connect(db: DbSession, shop: Shop, seller_id: str, token: str, client: KaspiClient, now: datetime) -> KaspiConnection:
    """Проверяет токен запросом к Kaspi и сохраняет его зашифрованным. Бросает KaspiAuthError / KaspiUnavailable."""
    client.ping(_now_ms(now))
    conn = db.get(KaspiConnection, shop.id)
    if conn is not None:
        # К-21: восстановление токена того же магазина в окно поддержки — данные и курсор синхронизации сохраняются
        conn.token_enc = encrypt_token(token)
        conn.status = "active"
        conn.last_error = None
        conn.reconnect_until = None
        db.add(conn)
        db.commit()
        return conn
    conn = KaspiConnection(shop_id=shop.id)
    conn.seller_id = seller_id
    conn.token_enc = encrypt_token(token)
    conn.price_key = secrets.token_urlsafe(24)
    conn.status = "active"
    conn.cursor_ms = None
    conn.backfill_done = False  # К-18.3: новое подключение — 90 дней догружаем заново
    conn.backfill_page = 0
    conn.load_done = 0
    conn.load_total = None
    conn.last_error = None
    conn.connected_at = now
    db.add(conn)
    db.commit()
    return conn


STORE_ID = re.compile(r"[A-Za-z0-9_-]{1,40}")


def set_store_ids(db: DbSession, shop_id: str, store_ids: list[str]) -> list[str]:
    """Коды складов Kaspi (storeId из кабинета «Склады и магазины»). Без них наличие в XML не передаётся."""
    clean = []
    for sid in store_ids:
        sid = sid.strip()
        if not STORE_ID.fullmatch(sid):
            raise ValueError(f"код склада не подходит: {sid!r}")
        if sid not in clean:
            clean.append(sid)
    conn = db.get(KaspiConnection, shop_id)
    if conn is None:
        raise KaspiUnavailable("Kaspi не подключён")
    conn.store_ids = ",".join(clean) or None
    db.add(conn)
    db.commit()
    return clean


def store_list(conn: KaspiConnection | None) -> list[str]:
    raw = getattr(conn, "store_ids", None) or "" if conn else ""
    return [x for x in raw.split(",") if x]


def disconnect(db: DbSession, shop_id: str) -> None:
    """Отключение в один шаг: токен и адрес прайс-листа удаляются, синхронизация останавливается.
    Загруженные заказы остаются: их удаление — отдельно по правилам хранения (раздел 9.3)."""
    conn = db.get(KaspiConnection, shop_id)
    if conn is not None:
        db.delete(conn)
        db.commit()


# ---------- синхронизация ----------

def _existing_orders(db: DbSession, shop_id: str, codes: list[str]) -> dict[str, Order]:
    if not codes:
        return {}
    rows = db.scalars(select(Order).where(Order.shop_id == shop_id, Order.number.in_(codes))).all()
    return {o.number: o for o in rows}


def _product_for(db: DbSession, shop_id: str, cache: dict[str, Product], offer: str, name: str,
                 category: str | None = None) -> Product:
    """Товар по артикулу. Название и категория из Kaspi (К-16.1, К-16.2) заменяют заглушки: название = артикул, категория по умолчанию."""
    product = cache.get(offer)
    if product is None:
        product = db.scalar(select(Product).where(Product.shop_id == shop_id, Product.sku == offer))
        if product is None:
            product = Product(id=_uid(), shop_id=shop_id, sku=offer, name=(name or offer)[:255],
                              category=(category or UNKNOWN_CATEGORY)[:120])
            db.add(product)
            db.flush()
        else:
            if name and name != offer and product.name == product.sku:
                product.name = name[:255]
            if category and product.category == UNKNOWN_CATEGORY:
                product.category = category[:120]
        cache[offer] = product
    return product


def _lines(client: KaspiClient, code: str) -> list[tuple[str, int, int, str | None, str | None]]:
    """Позиции заказа: (артикул, количество, цена). Позиция без артикула не теряет выручку: код строится из её id."""
    out = []
    for e in client.order_entries(code):
        sku, name = client.entry_product(e.entry_id)
        sku = sku or f"KX-{e.entry_id[:16]}"
        out.append((sku, e.qty, e.unit_price, name, e.category))
    return out


def _log_cancel(db: DbSession, shop: Shop, order: Order, product_id: str, qty: int, now: datetime) -> None:
    """Движение «отмена» в журнале склада (К-7): сколько штук Kaspi сняла с заказа."""
    from .models import StockMovement
    if qty > 0:
        db.add(StockMovement(id=_uid(), shop_id=shop.id, product_id=product_id, kind="cancel", qty=qty,
                             occurred_at=now, created_at=now))


def _reconcile(db: DbSession, shop: Shop, order: Order, lines: list[tuple[str, int, int, str | None, str | None]],
               products: dict[str, Product], now: datetime, seller_delivery: int | None = None,
               credit: bool = False) -> bool:
    """Приводит позиции заказа к данным Kaspi: количество, цена, удаление позиций, которых больше нет.
    Частичная отмена уменьшает количество — прибыль и остатки пересчитываются по позициям. Возвращает, менялось ли."""
    if not lines and order.status != "cancelled":
        # К-30, D8: пустой список позиций у неотменённого заказа — скорее сбой Kaspi, чем «всё отменено»:
        # не удаляем позиции (вместе с ними удалились бы возвраты и записался бы «cancel» в склад)
        log.warning("kaspi order %s: empty entries ignored", order.number)
        return False
    fresh: dict[str, tuple[int, int]] = {}  # product_id -> (количество, цена)
    for sku, qty, price, name, category in lines:
        product = _product_for(db, shop.id, products, sku, name or sku, category)
        q0, _p0 = fresh.get(product.id, (0, price))
        fresh[product.id] = (q0 + qty, price)
    # К-17.3/К-18: доставка продавца — расход заказа. Ставим её на первую позицию (сумма по заказу верна).
    # К-30 (найдено ручной сверкой): нет deliveryCostForSeller — продавец доставку не оплачивает, это 0, а не
    # «неизвестно». Иначе прибыль большинства заказов Kaspi не считалась. Сверить на реальном магазине (KASPI_TEST.md).
    delivery_by_pid: dict[str, int | None] = {pid: 0 for pid in fresh}
    if fresh and seller_delivery is not None:
        for i, pid in enumerate(fresh):
            delivery_by_pid[pid] = seller_delivery * 100 if i == 0 else 0
    # К-18: при рассрочке/кредите комиссия — ставка рассрочки (тариф продавца), а не ставка категории
    order_day = order.created_at.date() if order.created_at else None
    rate_bp = installment_rate_bp(db, shop.id, order_day) if credit else None
    existing: dict[str, list[OrderItem]] = {}
    for it in db.scalars(select(OrderItem).where(OrderItem.order_id == order.id)).all():
        existing.setdefault(it.product_id, []).append(it)
    changed = False
    for pid in set(existing) | set(fresh):
        items = existing.get(pid, [])
        qty, price = fresh.get(pid, (0, 0))
        if qty <= 0:  # позиции больше нет в заказе
            for it in items:
                _log_cancel(db, shop, order, pid, it.qty, now)
                db.delete(it)
                changed = True
            continue
        if not items:
            db.add(OrderItem(id=_uid(), order_id=order.id, shop_id=shop.id, product_id=pid, qty=qty,
                             unit_price_minor=price * 100, buyer_delivery_minor=delivery_by_pid.get(pid),
                             commission_rate_bp=rate_bp))
            changed = True
            continue
        keep, extra = items[0], items[1:]
        for it in extra:  # дубли одного товара в заказе сводим в одну позицию
            db.delete(it)
            changed = True
        if keep.qty > qty:  # частичная отмена: уменьшилось количество
            _log_cancel(db, shop, order, pid, keep.qty - qty, now)
        if keep.qty != qty or keep.unit_price_minor != price * 100:
            keep.qty = qty
            keep.unit_price_minor = price * 100
            changed = True
        if keep.buyer_delivery_minor != delivery_by_pid.get(pid):
            keep.buyer_delivery_minor = delivery_by_pid.get(pid)
            changed = True
        # К-30, D5: ставку уже записанной позиции не переписываем задним числом (смена тарифа — только для новых)
        if credit and keep.commission_rate_bp is None:
            keep.commission_rate_bp = rate_bp
            changed = True
        elif not credit and keep.commission_rate_bp is not None:
            keep.commission_rate_bp = None  # заказ перестал быть рассрочкой — ставка категории
            changed = True
    return changed


RETURN_WINDOW_DAYS = 14  # срок возврата по закону: 14 дней после получения покупателем
RETURN_GRACE_DAYS = 3  # запас на оформление возврата (К-19)


def return_window_open(order: Order, status: str, now: datetime) -> bool:
    """Нужно ли ещё следить за заказом (К-19): невыданные — до выдачи; выданные — 14 дней от выдачи + 3 дня запаса.
    Дата выдачи — completed_at (из атрибута Kaspi либо время, когда синхронизация впервые увидела «выдан»)."""
    if status in ("cancelled",):
        return False
    if status in ("pending", "in_progress") or order.completed_at is None:
        return True
    return now < _aware(order.completed_at) + timedelta(days=RETURN_WINDOW_DAYS + RETURN_GRACE_DAYS)


def _needs_refresh(order: Order, status: str, now: datetime) -> bool:
    return return_window_open(order, status, now)


def _ensure_full_return(db: DbSession, order: Order, now: datetime, to_warehouse: bool | None,
                        historic: bool = False) -> int:
    """2.5: заказ Kaspi в статусе RETURNED — возврат по каждой позиции на всё оставшееся количество.
    Без этого возвращённый заказ считался продажей: прибыль завышалась, остаток уменьшался.
    Повторный вызов ничего не добавляет. Комиссия считается возвращённой по ставке позиции (сверить на реальном магазине);
    годность товара — по returnedToWarehouse; неизвестно — None (остаток не увеличиваем, пока продавец не подтвердит)."""
    from sqlalchemy import func

    from .models import ReturnEvent
    from .money import apply_bp

    db.flush()  # позиции только что добавлены _reconcile; сессия без автосброса
    added = 0
    for item in db.scalars(select(OrderItem).where(OrderItem.order_id == order.id)).all():
        already = db.scalar(select(func.coalesce(func.sum(ReturnEvent.returned_qty), 0))
                            .where(ReturnEvent.item_id == item.id)) or 0
        left = item.qty - already
        if left <= 0:
            continue
        gross = item.unit_price_minor * left
        # К-30, D4: Kaspi не даёт дату возврата. Заказ увидели уже возвращённым (первая загрузка, догрузка) —
        # датируем выдачей, иначе все старые возвраты попали бы на день подключения; новый возврат — временем синхронизации
        when = (order.completed_at or now) if historic else now
        db.add(ReturnEvent(item_id=item.id, shop_id=order.shop_id, returned_qty=left, confirmed_at=when,
                           refund_minor=gross,
                           commission_returned_minor=(apply_bp(gross, item.commission_rate_bp)
                                                      if item.commission_rate_bp is not None else None),
                           delivery_returned_minor=0, reverse_delivery_minor=0,
                           goods_sellable=True if to_warehouse else None))
        added += 1
    if added:
        db.flush()
        reportcache.invalidate(order.shop_id)
    return added


def _apply_page(db: DbSession, shop: Shop, orders: list[KaspiOrder], products: dict[str, Product],
                now: datetime, client: KaspiClient, force_refresh: bool = False) -> tuple[int, int, int]:
    """Добавляет новые заказы, обновляет статусы и позиции. Возвращает (добавлено, обновлено статусы, изменено позиций)."""
    existing = _existing_orders(db, shop.id, [o.code for o in orders])
    added = updated = items_changed = 0
    for ko in orders:
        status = STATE_MAP.get(ko.state, DEFAULT_STATUS)
        completed_at = _utc(ko.completed_ms) if ko.completed_ms else None
        order = existing.get(ko.code)
        if order is None:
            if status in ("completed", "returned") and completed_at is None:
                completed_at = now
            order = Order(id=_uid(), shop_id=shop.id, number=ko.code, status=status,
                          created_at=_utc(ko.created_ms), completed_at=completed_at)
            db.add(order)
            db.flush()
            _reconcile(db, shop, order, _lines(client, ko.code), products, now, ko.seller_delivery, ko.credit)
            if status == "returned":
                _ensure_full_return(db, order, now, ko.returned_to_warehouse, historic=True)
            added += 1
            continue
        if order.status != status:
            order.status = status
            updated += 1
        if order.completed_at is None and status in ("completed", "returned"):
            order.completed_at = completed_at or now
        if force_refresh or _needs_refresh(order, status, now):
            if _reconcile(db, shop, order, _lines(client, ko.code), products, now, ko.seller_delivery, ko.credit):
                items_changed += 1
        if status == "returned":
            _ensure_full_return(db, order, now, ko.returned_to_warehouse)
    return added, updated, items_changed


class KaspiBusy(Exception):
    """Синхронизация этого магазина уже идёт (ручная или фоновая): второй запуск не начинаем (К-17.3)."""


_SHOP_LOCKS: dict[str, threading.Lock] = {}
_SHOP_LOCKS_GUARD = threading.Lock()


def sync(db: DbSession, conn: KaspiConnection, client: KaspiClient, now: datetime) -> dict:
    """Один проход синхронизации под блокировкой магазина: параллельные запуски не начинаются (KaspiBusy)."""
    with _SHOP_LOCKS_GUARD:
        lock = _SHOP_LOCKS.setdefault(conn.shop_id, threading.Lock())
    if not lock.acquire(blocking=False):
        raise KaspiBusy("синхронизация уже идёт")
    try:
        return _sync_locked(db, conn, client, now)
    finally:
        lock.release()


def _sync_locked(db: DbSession, conn: KaspiConnection, client: KaspiClient, now: datetime) -> dict:
    """Один проход синхронизации. Заказы сохраняются после каждой страницы, а курсор — только после полного прохода.

    Почему так (К-17.3): порядок выдачи Kaspi не описан. Если страницы идут «новые сначала», курсор по последней
    странице пропустил бы старые заказы при сбое посреди первой загрузки. Теперь при сбое курсор остаётся прежним,
    повторный запуск читает окно заново; заказы не дублируются (уникальность по номеру заказа).
    При ошибке токена статус становится token_invalid; при недоступности Kaspi — last_error.
    """
    shop = db.get(Shop, conn.shop_id)
    if shop is None:
        raise KaspiUnavailable("магазин не найден")
    if conn.cursor_ms is not None:
        since = conn.cursor_ms - OVERLAP_MS
    else:
        since = _now_ms(now) - FIRST_STAGE_DAYS * 86_400_000  # этап 1 первой загрузки: последние 7 дней
    products: dict[str, Product] = {}
    added = updated = pages = items_changed = 0
    newest_overall = 0
    first_load = conn.cursor_ms is None
    stage_total = None
    try:
        page = 0
        while True:
            orders, total = client.list_orders_page(since_ms=since, page=page)
            if page == 0 and first_load:
                stage_total = total
            if not orders:
                break
            a, u, c = _apply_page(db, shop, orders, products, now, client)
            added += a
            updated += u
            items_changed += c
            pages += 1
            if first_load:
                conn.load_done = (conn.load_done or 0) + len(orders)
                if stage_total is not None:
                    conn.load_total = stage_total
            newest_overall = max(newest_overall, max(o.created_ms for o in orders))
            if client.last_point_id and not conn.store_ids:  # подсказка только пока код склада не задан
                conn.store_hint = client.last_point_id
            conn.last_error = None
            db.commit()
            if len(orders) < PAGE_SIZE:
                break
            page += 1
        # курсор двигаем только когда весь проход завершён
        if newest_overall:
            conn.cursor_ms = max(conn.cursor_ms or 0, newest_overall)
            db.add(conn)
            db.commit()
        # этап 2: догрузка остальных 90 дней постранично (продолжается с сохранённой страницы)
        if not conn.backfill_done:
            b = _backfill_pass(db, shop, conn, client, now, products)
            added += b["added"]
            updated += b["updated"]
            items_changed += b["items_changed"]
            pages += b["pages"]
    except KaspiAuthError:
        db.rollback()
        conn.status = "token_invalid"
        conn.last_error = "Kaspi не принимает токен. Проверьте, что ключ не отозван, и подключите магазин заново."
        db.add(conn)
        db.commit()
        raise
    except KaspiUnavailable:
        db.rollback()
        conn.last_error = "Kaspi недоступен. Синхронизация повторится позже."
        db.add(conn)
        db.commit()
        raise
    conn.last_sync_at = now
    conn.status = "active"
    db.add(conn)
    db.commit()
    reportcache.invalidate(shop.id)  # AUD-12: появились новые заказы
    return {"pages": pages, "added": added, "updated": updated, "items_changed": items_changed}


def _backfill_pass(db: DbSession, shop: Shop, conn: KaspiConnection, client: KaspiClient, now: datetime,
                   products: dict[str, Product]) -> dict:
    """Догрузка заказов за 90 дней без последних 7 (К-18.3). Страница сохраняется после каждой, поэтому
    следующий запуск продолжает с неё; заказы не дублируются. Прогресс: load_done / load_total."""
    since = _now_ms(now) - FIRST_SYNC_DAYS * 86_400_000
    until = _now_ms(now) - FIRST_STAGE_DAYS * 86_400_000
    page = conn.backfill_page or 0
    added = updated = items_changed = pages = 0
    while True:
        orders, total = client.list_orders_page(since_ms=since, page=page, until_ms=until)
        if page == 0 and total is not None:
            # прогресс: всего = этап 1 (7 дней) + догрузка. При повторе страницы 0 после сбоя возможна погрешность
            conn.load_total = (conn.load_total or 0) + total
        if not orders:
            conn.backfill_done = True
            conn.backfill_page = 0
            db.add(conn)
            db.commit()
            break
        a, u, c = _apply_page(db, shop, orders, products, now, client)
        added += a
        updated += u
        items_changed += c
        pages += 1
        conn.load_done = (conn.load_done or 0) + len(orders)
        conn.backfill_page = page + 1
        db.add(conn)
        db.commit()
        if len(orders) < PAGE_SIZE:
            conn.backfill_done = True
            conn.backfill_page = 0
            db.add(conn)
            db.commit()
            break
        page += 1
    return {"added": added, "updated": updated, "items_changed": items_changed, "pages": pages}


def client_for(conn: KaspiConnection) -> KaspiClient:
    """Клиент с токеном из базы. Тесты подменяют эту функцию на клиент с моком."""
    return KaspiClient(decrypt_token(conn.token_enc))


# ---------- XML-прайс ----------

KASPI_NS = "kaspiShopping"
XSI_NS = "http://www.w3.org/2001/XMLSchema-instance"


MAX_CATALOG_BYTES = 20 * 1024 * 1024
MAX_OFFERS = 50_000


class KaspiNoCatalog(Exception):
    """Прайс продавца ещё не импортирован: ссылку на прайс не показываем (К-16.3)."""


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def import_catalog(db: DbSession, shop_id: str, data: bytes, now: datetime) -> int:
    """Импорт прайса продавца (файл из кабинета Kaspi). Возвращает число предложений. Бросает ValueError при плохом файле."""
    if len(data) > MAX_CATALOG_BYTES:
        raise ValueError("файл больше 20 МБ")
    head = data[:4096].upper()
    if b"<!DOCTYPE" in head or b"<!ENTITY" in data.upper():
        raise ValueError("файл с описанием DTD или сущностями не принимается")
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise ValueError("не удалось разобрать XML") from exc
    if _local(root.tag) != "kaspi_catalog":
        raise ValueError("это не прайс-лист Kaspi (нет корня kaspi_catalog)")
    offers = [el for el in root.iter() if _local(el.tag) == "offer"]
    if not offers:
        raise ValueError("в файле нет предложений")
    if len(offers) > MAX_OFFERS:
        raise ValueError(f"слишком много предложений: больше {MAX_OFFERS}")
    text = ET.tostring(root, encoding="unicode")
    row = db.get(KaspiCatalog, shop_id)
    if row is None:
        row = KaspiCatalog(shop_id=shop_id)
    row.xml_text = text
    row.offers_count = len(offers)
    row.imported_at = now
    db.add(row)
    db.commit()
    return len(offers)


def get_catalog(db: DbSession, shop_id: str) -> KaspiCatalog | None:
    return db.get(KaspiCatalog, shop_id)


def catalog_stock_hints(db: DbSession, shop_id: str) -> dict[str, int]:
    """К-24: остатки из прайса продавца (stockCount по всем складам предложения) — подсказка для поля остатка."""
    row = db.get(KaspiCatalog, shop_id)
    if row is None:
        return {}
    try:
        root = ET.fromstring(row.xml_text)
    except ET.ParseError:
        return {}
    hints: dict[str, int] = {}
    for offer in (el for el in root.iter() if _local(el.tag) == "offer"):
        sku = (offer.get("sku") or "").strip()
        counts = [a.get("stockCount") for a in offer.iter() if _local(a.tag) == "availability"]
        nums = [int(c) for c in counts if c is not None and c.strip().isdigit()]
        if sku and nums:
            hints[sku] = sum(nums)
    return hints


def price_list_xml(db: DbSession, shop: Shop, conn: KaspiConnection, today: date | None = None) -> bytes:
    """Наш файл для кабинета Kaspi: весь импортированный каталог продавца с его ценами и названиями.
    Меняем только наличие и остатки по складам (если указаны коды складов). Снятые с продажи — available="no", stockCount="0".
    Без кодов складов наличие не передаём: файл продавца остаётся как есть, снятие с продажи не применяется (это записано в комментарии)."""
    from .models import Product as _Product, ProductStock
    from .stock import stock_states

    catalog = get_catalog(db, shop.id)
    if catalog is None:
        raise KaspiNoCatalog("прайс продавца не импортирован")
    ET.register_namespace("", KASPI_NS)
    ET.register_namespace("xsi", XSI_NS)
    root = ET.fromstring(catalog.xml_text.encode("utf-8"))
    root.set("date", (today or date.today()).isoformat())

    stores = store_list(conn)
    states = stock_states(db, shop) if stores else {}
    delisted = set(db.scalars(select(ProductStock.product_id).where(ProductStock.shop_id == shop.id, ProductStock.delisted.is_(True))).all())
    sku_to_pid = {sku: pid for pid, sku in db.execute(select(_Product.id, _Product.sku).where(_Product.shop_id == shop.id)).all()}
    untouched_delisted = 0
    for offer in [el for el in root.iter() if _local(el.tag) == "offer"]:
        sku = offer.get("sku")
        pid = sku_to_pid.get(sku or "")
        if pid is None:
            continue  # товара нет в нашей системе: остаётся как в файле продавца
        if not stores:
            if pid in delisted:
                untouched_delisted += 1
            continue
        ns = offer.tag[: offer.tag.index("}") + 1] if offer.tag.startswith("{") else ""
        for old in [el for el in offer if _local(el.tag) == "availabilities"]:
            offer.remove(old)
        av_el = ET.Element(f"{ns}availabilities")
        qty = max(states[pid].current, 0) if pid in states else 0
        for sid in stores:
            if pid in delisted:
                ET.SubElement(av_el, f"{ns}availability", available="no", storeId=sid, stockCount="0")
            else:
                ET.SubElement(av_el, f"{ns}availability", available="yes" if qty > 0 else "no", storeId=sid, stockCount=str(qty))
        # availabilities ставим перед ценой, как в описании формата
        children = list(offer)
        idx = next((i for i, el in enumerate(children) if _local(el.tag) == "price"), len(children))
        offer.insert(idx, av_el)
    body = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    if untouched_delisted:
        note = (f"<!-- снятие с продажи не передано для {untouched_delisted} товаров: не указаны коды складов (storeId) -->"
                ).encode("utf-8")
        body = body.replace(b"?>", b"?>" + note, 1) if body.startswith(b"<?xml") else note + body
    return body


def find_by_price_key(db: DbSession, shop_id: str, price_key: str) -> KaspiConnection | None:
    conn = db.get(KaspiConnection, shop_id)
    if conn is None or not secrets.compare_digest(conn.price_key, price_key):
        return None
    return conn




SYNC_EVERY = 15 * 60  # ТЗ: новые заказы — каждые 15 минут


INSTALLMENT_CATEGORY = "Рассрочка Kaspi"  # категория тарифа в настройках комиссий продавца
INSTALLMENT_DEFAULT_BP = 1090  # 10,9% — ставка продажи в рассрочку по официальной странице Kaspi (К-18); продавец может изменить


def installment_rate_bp(db: DbSession, shop_id: str, day: date | None = None) -> int:
    """Тариф рассрочки продавца на дату заказа (К-30, D5: раньше бралась самая поздняя ставка, даже будущая)."""
    from .models import CommissionPreset
    q = select(CommissionPreset).where(CommissionPreset.shop_id == shop_id,
                                       CommissionPreset.category == INSTALLMENT_CATEGORY)
    if day is not None:
        q = q.where((CommissionPreset.effective_from.is_(None)) | (CommissionPreset.effective_from <= day))
    row = db.scalar(q.order_by(CommissionPreset.effective_from.desc()).limit(1))
    return row.rate_bp if row is not None else INSTALLMENT_DEFAULT_BP


MAX_OPEN_REFRESH = 2000  # за один суточный проход (К-19)


def refresh_open_orders(db: DbSession, conn: KaspiConnection, client: KaspiClient, now: datetime) -> dict:
    """Суточная проверка открытых заказов (К-19): по каждому заказу, у которого окно возврата ещё открыто, —
    запрос по номеру (filter[orders][code]). Заказы с датой создания старше окна обычной синхронизации тоже видны."""
    with _SHOP_LOCKS_GUARD:
        lock = _SHOP_LOCKS.setdefault(conn.shop_id, threading.Lock())
    if not lock.acquire(blocking=False):
        raise KaspiBusy("синхронизация уже идёт")
    try:
        return _refresh_open_locked(db, conn, client, now)
    finally:
        lock.release()


def _refresh_open_locked(db: DbSession, conn: KaspiConnection, client: KaspiClient, now: datetime) -> dict:
    shop = db.get(Shop, conn.shop_id)
    if shop is None:
        raise KaspiUnavailable("магазин не найден")
    # К-30, D2: в SQL — только заказы, за которыми ещё следим (не выданы или выданы не раньше 14 + 3 дней),
    # свежие первыми. Раньше брались 2000 самых старых неотменённых — у крупного магазина свежие не проверялись.
    from sqlalchemy import or_

    window_start = now - timedelta(days=RETURN_WINDOW_DAYS + RETURN_GRACE_DAYS)
    candidates = db.scalars(
        select(Order).where(Order.shop_id == shop.id, Order.status != "cancelled",
                            or_(Order.status.in_(("pending", "in_progress")), Order.completed_at.is_(None),
                                Order.completed_at >= window_start))
        .order_by(Order.created_at.desc()).limit(MAX_OPEN_REFRESH)
    ).all()
    products: dict[str, Product] = {}
    checked = updated = items_changed = 0
    try:
        for order in candidates:
            if not return_window_open(order, order.status, now):
                continue
            ko = client.order_by_code(order.number)
            checked += 1
            if ko is None:
                continue
            status = STATE_MAP.get(ko.state, DEFAULT_STATUS)
            if order.status != status:
                order.status = status
                updated += 1
            if order.completed_at is None and status in ("completed", "returned"):
                order.completed_at = _utc(ko.completed_ms) if ko.completed_ms else now
            if return_window_open(order, status, now) and _reconcile(
                    db, shop, order, _lines(client, order.number), products, now, ko.seller_delivery, ko.credit):
                items_changed += 1
            if status == "returned":
                _ensure_full_return(db, order, now, ko.returned_to_warehouse)
            db.commit()
    except KaspiAuthError:
        db.rollback()
        conn.status = "token_invalid"
        db.add(conn)
        db.commit()
        raise
    return {"checked": checked, "updated": updated, "items_changed": items_changed}


def sync_due(db: DbSession, now: datetime, limit: int = 50) -> list[tuple[str, str]]:
    """Синхронизирует подключения, у которых давно не было синхронизации. Возвращает (магазин, итог)."""
    cutoff = now - timedelta(seconds=SYNC_EVERY)
    due = db.scalars(
        select(KaspiConnection).where(
            KaspiConnection.status == "active",
            (KaspiConnection.last_sync_at.is_(None)) | (KaspiConnection.last_sync_at < cutoff),
        ).limit(limit)
    ).all()
    from .accounts import deactivated_shop_ids

    paused = deactivated_shop_ids(db)  # К-21: деактивированный аккаунт — синхронизация стоит
    done: list[tuple[str, str]] = []
    for conn in due:
        if conn.shop_id in paused:
            continue
        client = None
        try:
            client = client_for(conn)
            sync(db, conn, client, now)
            done.append((conn.shop_id, "synced"))
        except KaspiBusy:
            done.append((conn.shop_id, "busy"))
        except KaspiAuthError:
            done.append((conn.shop_id, "token_invalid"))
        except KaspiUnavailable:
            done.append((conn.shop_id, "unavailable"))
        except Exception:  # noqa: BLE001 — один магазин не должен остановить остальные; подробности — в журнале
            log.exception("kaspi sync failed for shop %s", conn.shop_id)
            db.rollback()
            done.append((conn.shop_id, "error"))
        finally:
            if client is not None:
                client.close()
    return done
