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
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from . import reportcache
from .config import settings
from .kaspi_client import PAGE_SIZE, KaspiAuthError, KaspiClient, KaspiOrder, KaspiUnavailable
from .models import KaspiConnection, Order, OrderItem, Product, Shop, _uid

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
# Повторно читаем заказы за 14 дней до курсора: Kaspi меняет состояние заказа позже (возврат, отмена).
OVERLAP_MS = 14 * 86_400_000
UNKNOWN_CATEGORY = "Без категории"


# ---------- шифрование токена ----------

def _fernet() -> Fernet:
    if settings.kaspi_key:
        return Fernet(settings.kaspi_key.encode())
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
    conn = db.get(KaspiConnection, shop.id) or KaspiConnection(shop_id=shop.id)
    conn.seller_id = seller_id
    conn.token_enc = encrypt_token(token)
    conn.price_key = secrets.token_urlsafe(24)
    conn.status = "active"
    conn.cursor_ms = None
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


def _product_for(db: DbSession, shop_id: str, cache: dict[str, Product], offer: str, name: str) -> Product:
    product = cache.get(offer)
    if product is None:
        product = db.scalar(select(Product).where(Product.shop_id == shop_id, Product.sku == offer))
        if product is None:
            product = Product(id=_uid(), shop_id=shop_id, sku=offer, name=name[:255], category=UNKNOWN_CATEGORY)
            db.add(product)
            db.flush()
        cache[offer] = product
    return product


def _lines(client: KaspiClient, code: str) -> list[tuple[str, int, int]]:
    """Позиции заказа: (артикул, количество, цена). Позиция без артикула не теряет выручку: код строится из её id."""
    out = []
    for e in client.order_entries(code):
        sku = client.entry_sku(e.entry_id) or f"KX-{e.entry_id[:16]}"
        out.append((sku, e.qty, e.unit_price))
    return out


def _reconcile(db: DbSession, shop: Shop, order: Order, lines: list[tuple[str, int, int]],
               products: dict[str, Product]) -> bool:
    """Приводит позиции заказа к данным Kaspi: количество, цена, удаление позиций, которых больше нет.
    Частичная отмена уменьшает количество — прибыль и остатки пересчитываются по позициям. Возвращает, менялось ли."""
    fresh: dict[str, tuple[int, int]] = {}  # product_id -> (количество, цена)
    for sku, qty, price in lines:
        product = _product_for(db, shop.id, products, sku, sku)
        q0, _p0 = fresh.get(product.id, (0, price))
        fresh[product.id] = (q0 + qty, price)
    existing: dict[str, list[OrderItem]] = {}
    for it in db.scalars(select(OrderItem).where(OrderItem.order_id == order.id)).all():
        existing.setdefault(it.product_id, []).append(it)
    changed = False
    for pid in set(existing) | set(fresh):
        items = existing.get(pid, [])
        qty, price = fresh.get(pid, (0, 0))
        if qty <= 0:  # позиции больше нет в заказе
            for it in items:
                db.delete(it)
                changed = True
            continue
        if not items:
            db.add(OrderItem(id=_uid(), order_id=order.id, shop_id=shop.id, product_id=pid, qty=qty,
                             unit_price_minor=price * 100, buyer_delivery_minor=None, commission_rate_bp=None))
            changed = True
            continue
        keep, extra = items[0], items[1:]
        for it in extra:  # дубли одного товара в заказе сводим в одну позицию
            db.delete(it)
            changed = True
        if keep.qty != qty or keep.unit_price_minor != price * 100:
            keep.qty = qty
            keep.unit_price_minor = price * 100
            changed = True
    return changed


def _needs_refresh(order: Order, status: str, now: datetime) -> bool:
    """Позиции перечитываем у незавершённых заказов и у выполненных за последние 14 дней (там бывают частичные отмены).
    Остальные — не трогаем, чтобы не делать по запросу на каждый заказ при каждой синхронизации."""
    if status in ("pending", "in_progress"):
        return True
    if order.completed_at is not None:
        return _aware(order.completed_at) >= now - timedelta(milliseconds=OVERLAP_MS)
    return False


def _apply_page(db: DbSession, shop: Shop, orders: list[KaspiOrder], products: dict[str, Product],
                now: datetime, client: KaspiClient) -> tuple[int, int, int]:
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
            _reconcile(db, shop, order, _lines(client, ko.code), products)
            added += 1
            continue
        if order.status != status:
            order.status = status
            updated += 1
        if order.completed_at is None and status in ("completed", "returned"):
            order.completed_at = completed_at or now
        if _needs_refresh(order, status, now):
            if _reconcile(db, shop, order, _lines(client, ko.code), products):
                items_changed += 1
    return added, updated, items_changed


def sync(db: DbSession, conn: KaspiConnection, client: KaspiClient, now: datetime) -> dict:
    """Один проход синхронизации. Курсор сохраняется после каждой страницы.

    При ошибке токена статус становится token_invalid; при недоступности Kaspi — last_error, курсор не сдвигается
    за обработанное. Повторный запуск продолжает с курсора и не дублирует заказы.
    """
    shop = db.get(Shop, conn.shop_id)
    if shop is None:
        raise KaspiUnavailable("магазин не найден")
    if conn.cursor_ms is not None:
        since = conn.cursor_ms - OVERLAP_MS
    else:
        since = _now_ms(now) - FIRST_SYNC_DAYS * 86_400_000
    products: dict[str, Product] = {}
    added = updated = pages = items_changed = 0
    try:
        page = 0
        while True:
            orders = client.list_orders(since_ms=since, page=page)
            if not orders:
                break
            a, u, c = _apply_page(db, shop, orders, products, now, client)
            added += a
            updated += u
            items_changed += c
            pages += 1
            newest = max(o.created_ms for o in orders)
            conn.cursor_ms = max(conn.cursor_ms or 0, newest)
            conn.last_error = None
            db.commit()
            if len(orders) < PAGE_SIZE:
                break
            page += 1
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


def client_for(conn: KaspiConnection) -> KaspiClient:
    """Клиент с токеном из базы. Тесты подменяют эту функцию на клиент с моком."""
    return KaspiClient(decrypt_token(conn.token_enc))


# ---------- XML-прайс ----------

KASPI_NS = "kaspiShopping"
XSI_NS = "http://www.w3.org/2001/XMLSchema-instance"


def price_list_xml(db: DbSession, shop: Shop, conn: KaspiConnection, today: date | None = None) -> bytes:
    """Прайс: цена — последняя продажная цена товара из заказов. UNVERIFIED: формат сверить с документацией Kaspi.
    Остатков Satti не ведёт, поэтому наличие не указывается."""
    rows = db.execute(
        select(Product.id, Product.sku, Product.name, OrderItem.unit_price_minor, Order.created_at)
        .join(OrderItem, OrderItem.product_id == Product.id)
        .join(Order, Order.id == OrderItem.order_id)
        .where(Product.shop_id == shop.id)
        .order_by(Order.created_at.desc())
    ).all()
    from .models import ProductStock  # снятые с продажи (склад)
    from .stock import stock_states
    delisted = set(db.scalars(select(ProductStock.product_id).where(ProductStock.shop_id == shop.id, ProductStock.delisted.is_(True))).all())
    stores = store_list(conn)
    states = stock_states(db, shop) if stores else {}
    # документация Kaspi: sku — латиница и цифры до 20 знаков, уникален в файле
    offers: dict[str, tuple[str, int, str]] = {}  # sku -> (название, цена тенге, product_id)
    skipped: list[str] = []
    for pid, sku, name, price_minor, _created in rows:
        if not re.fullmatch(r"[A-Za-z0-9]{1,20}", sku or ""):
            if sku and sku not in skipped:
                skipped.append(sku)
            continue
        if sku not in offers:
            offers[sku] = (name, price_minor // 100, pid)
    ET.register_namespace("", KASPI_NS)
    ET.register_namespace("xsi", XSI_NS)
    root = ET.Element(f"{{{KASPI_NS}}}kaspi_catalog", {
        "date": (today or date.today()).isoformat(),
        f"{{{XSI_NS}}}schemaLocation": f"{KASPI_NS} http://kaspi.kz/kaspishopping.xsd"})
    ET.SubElement(root, f"{{{KASPI_NS}}}company").text = shop.name
    ET.SubElement(root, f"{{{KASPI_NS}}}merchantid").text = conn.seller_id
    offers_el = ET.SubElement(root, f"{{{KASPI_NS}}}offers")
    for sku, (name, price, pid) in sorted(offers.items()):
        delisted_now = pid in delisted
        if not stores and delisted_now:
            continue  # без кодов складов снятый товар нельзя описать наличием — остаётся вне файла (см. комментарий)
        offer = ET.SubElement(offers_el, f"{{{KASPI_NS}}}offer", sku=sku)
        ET.SubElement(offer, f"{{{KASPI_NS}}}model").text = name
        if stores:
            # снятие с продажи — available="no" и stockCount="0" на всех складах (обратимо, без удаления из файла)
            qty = max(states[pid].current, 0) if pid in states else 0
            av_el = ET.SubElement(offer, f"{{{KASPI_NS}}}availabilities")
            for sid in stores:
                if delisted_now:
                    ET.SubElement(av_el, f"{{{KASPI_NS}}}availability", available="no", storeId=sid, stockCount="0")
                else:
                    ET.SubElement(av_el, f"{{{KASPI_NS}}}availability",
                                  available="yes" if qty > 0 else "no", storeId=sid, stockCount=str(qty))
        ET.SubElement(offer, f"{{{KASPI_NS}}}price").text = str(price)
    notes = []
    if skipped:
        notes.append("не переданы, артикул не латиница/цифры до 20 знаков: " + ", ".join(skipped[:50]))
    if not stores:
        notes.append("наличие не передаётся: не указаны коды складов (storeId); снятые с продажи товары не включены")
    body = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    if notes:  # комментарий в файле: что не передано и почему (см. docs/kaspi-assumptions.md)
        note = ("<!-- " + "; ".join(n.replace("--", "-") for n in notes) + " -->").encode("utf-8")
        body = body.replace(b"?>", b"?>" + note, 1) if body.startswith(b"<?xml") else note + body
    return body


def find_by_price_key(db: DbSession, shop_id: str, price_key: str) -> KaspiConnection | None:
    conn = db.get(KaspiConnection, shop_id)
    if conn is None or not secrets.compare_digest(conn.price_key, price_key):
        return None
    return conn




SYNC_EVERY = 15 * 60  # ТЗ: новые заказы — каждые 15 минут


def sync_due(db: DbSession, now: datetime, limit: int = 50) -> list[tuple[str, str]]:
    """Синхронизирует подключения, у которых давно не было синхронизации. Возвращает (магазин, итог)."""
    cutoff = now - timedelta(seconds=SYNC_EVERY)
    due = db.scalars(
        select(KaspiConnection).where(
            KaspiConnection.status == "active",
            (KaspiConnection.last_sync_at.is_(None)) | (KaspiConnection.last_sync_at < cutoff),
        ).limit(limit)
    ).all()
    done: list[tuple[str, str]] = []
    for conn in due:
        client = None
        try:
            client = client_for(conn)
            sync(db, conn, client, now)
            done.append((conn.shop_id, "synced"))
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
