"""Подключение магазина Kaspi: токен, синхронизация заказов, XML-прайс (этап 2, задачи 2.2–2.4).

- Токен хранится только зашифрованным (Fernet, ключ SATTI_KASPI_KEY). В ответах API и журнале его нет.
- Синхронизация идемпотентна: заказ с тем же номером обновляется, а не дублируется. Курсор (время самого свежего
  обработанного заказа) сохраняется после каждой страницы, поэтому сбой не теряет уже обработанное.
- Прайс-лист отдаётся по адресу с секретом (price_key), который меняется при каждом подключении.
"""

from __future__ import annotations

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


def _apply_page(db: DbSession, shop: Shop, orders: list[KaspiOrder], products: dict[str, Product],
                now: datetime) -> tuple[int, int]:
    """Добавляет новые заказы и обновляет статусы уже известных. Возвращает (добавлено, обновлено)."""
    existing = _existing_orders(db, shop.id, [o.code for o in orders])
    added = updated = 0
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
            for entry in ko.entries:
                product = _product_for(db, shop.id, products, entry.offer_code, entry.name)
                db.add(OrderItem(id=_uid(), order_id=order.id, shop_id=shop.id, product_id=product.id,
                                 qty=entry.qty, unit_price_minor=entry.unit_price * 100,
                                 buyer_delivery_minor=None, commission_rate_bp=None))
            added += 1
            continue
        if order.status != status:
            order.status = status
            updated += 1
        if order.completed_at is None and status in ("completed", "returned"):
            order.completed_at = completed_at or now
    return added, updated


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
    added = updated = pages = 0
    try:
        page = 0
        while True:
            orders = client.list_orders(since_ms=since, page=page)
            if not orders:
                break
            a, u = _apply_page(db, shop, orders, products, now)
            added += a
            updated += u
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
    return {"pages": pages, "added": added, "updated": updated}


def client_for(conn: KaspiConnection) -> KaspiClient:
    """Клиент с токеном из базы. Тесты подменяют эту функцию на клиент с моком."""
    return KaspiClient(decrypt_token(conn.token_enc))


# ---------- XML-прайс ----------

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
    offers: dict[str, tuple[str, int]] = {}
    for pid, sku, name, price_minor, _created in rows:
        if sku not in offers:
            offers[sku] = (name, price_minor // 100)
    root = ET.Element("kaspi_catalog", date=(today or date.today()).isoformat())
    ET.SubElement(root, "company").text = shop.name
    ET.SubElement(root, "merchantid").text = conn.seller_id
    offers_el = ET.SubElement(root, "offers")
    for sku, (name, price) in sorted(offers.items()):
        offer = ET.SubElement(offers_el, "offer", sku=sku)
        ET.SubElement(offer, "model").text = name
        ET.SubElement(offer, "price").text = str(price)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


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
