"""Модель данных (docs/spec.md, раздел 10) — объём этапа A (демо) и заготовки для бета-этапа.

Деньги — BigInteger в тиынах. Ставки — в базисных пунктах. Даты — UTC.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from .timeutil import utc_now

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    false,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def _uid() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return utc_now()


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uid)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    locale: Mapped[str] = mapped_column(String(8), default="ru")
    age_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)  # 18+ (ADR-0004)
    terms_version: Mapped[str | None] = mapped_column(String(32), nullable=True)  # версия условий и политики, которую согласился пользователь (1.19)
    terms_accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    blocked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)  # блокировка администратором
    support_access_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)  # доступ поддержки, 24 ч
    # К-21: деактивация на 30 дней — доступ закрыт, фоновое остановлено; delete_after — дата автоудаления
    deactivated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delete_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    # К-21, часть 2, п.6: обучение пройдено — на втором устройстве того же аккаунта не повторяется
    onboarding_done_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    ai_consent_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    ai_consent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ai_consent_revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AuthCode(Base):
    __tablename__ = "auth_codes"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uid)
    email: Mapped[str] = mapped_column(String(255), index=True)
    purpose: Mapped[str] = mapped_column(String(16), default="login")  # login | delete
    user_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    code_hash: Mapped[str] = mapped_column(String(128))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    used: Mapped[bool] = mapped_column(Boolean, default=False)


class Session(Base):
    __tablename__ = "sessions"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uid)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=True)
    demo_shop_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    access_hash: Mapped[str] = mapped_column(String(128), index=True)
    refresh_hash: Mapped[str] = mapped_column(String(128), index=True)
    access_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    refresh_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)


class DemoInstallation(Base):
    __tablename__ = "demo_installations"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # хеш id установки
    shop_id: Mapped[str] = mapped_column(String(32))
    last_active_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, default=_now)  # ADR-0005: демо живёт 24 часа от создания
    ai_consent_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    ai_consent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ai_consent_revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Shop(Base):
    __tablename__ = "shops"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uid)
    owner_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    name: Mapped[str] = mapped_column(String(120))
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Almaty")
    language: Mapped[str] = mapped_column(String(8), default="ru")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    # К-33 А2: «Я плательщик НДС». Плательщик: выручка без НДС, комиссия и доставка без НДС (НДС к зачёту).
    vat_payer: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    # К-33 А3: режим презентации — включает владелец в админке; пример остатков и себестоимости на данных продавца
    presentation_mode: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    example_cost_pct: Mapped[int] = mapped_column(Integer, default=60, server_default="60")

    products: Mapped[list["Product"]] = relationship(cascade="all, delete-orphan", passive_deletes=True)
    orders: Mapped[list["Order"]] = relationship(cascade="all, delete-orphan", passive_deletes=True)


class Product(Base):
    __tablename__ = "products"
    __table_args__ = (UniqueConstraint("shop_id", "sku", name="uq_product_sku"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uid)
    shop_id: Mapped[str] = mapped_column(ForeignKey("shops.id", ondelete="CASCADE"), index=True)
    sku: Mapped[str] = mapped_column(String(64))  # артикул, текст
    name: Mapped[str] = mapped_column(String(255))
    category: Mapped[str] = mapped_column(String(120), default="Без категории")


class ProductCostVersion(Base):
    """Версия затрат на единицу. effective_from пусто — с начала истории."""

    __tablename__ = "product_cost_versions"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uid)
    shop_id: Mapped[str] = mapped_column(ForeignKey("shops.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[str] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), index=True)
    purchase_minor: Mapped[int] = mapped_column(BigInteger)
    delivery_to_warehouse_minor: Mapped[int] = mapped_column(BigInteger, default=0)
    packaging_minor: Mapped[int] = mapped_column(BigInteger, default=0)
    other_minor: Mapped[int] = mapped_column(BigInteger, default=0)
    effective_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    source: Mapped[str] = mapped_column(String(32), default="manual")  # manual | import | demo | example (К-33 А3)
    import_batch_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    cancelled: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    @property
    def landed_unit_minor(self) -> int:
        return (
            self.purchase_minor
            + self.delivery_to_warehouse_minor
            + self.packaging_minor
            + self.other_minor
        )


class CommissionPreset(Base):
    __tablename__ = "commission_presets"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uid)
    shop_id: Mapped[str] = mapped_column(ForeignKey("shops.id", ondelete="CASCADE"), index=True)
    category: Mapped[str] = mapped_column(String(120))
    rate_bp: Mapped[int] = mapped_column(Integer)
    effective_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    source: Mapped[str] = mapped_column(String(32), default="manual")  # manual | demo
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    demo: Mapped[bool] = mapped_column(Boolean, default=False)


class TaxRate(Base):
    """Версия ставки налога магазина (ТЗ 2.1, раздел 7). rate_bp = None — налог выключен с этой даты."""

    __tablename__ = "tax_rates"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uid)
    shop_id: Mapped[str] = mapped_column(ForeignKey("shops.id", ondelete="CASCADE"), index=True)
    rate_bp: Mapped[int | None] = mapped_column(Integer, nullable=True)
    effective_from: Mapped[date | None] = mapped_column(Date, nullable=True)  # None — ко всей истории
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Order(Base):
    __tablename__ = "orders"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uid)
    shop_id: Mapped[str] = mapped_column(ForeignKey("shops.id", ondelete="CASCADE"), index=True)
    number: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(24))  # completed|cancelled|pending|in_progress|returned|partial_return
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    items: Mapped[list["OrderItem"]] = relationship(cascade="all, delete-orphan", passive_deletes=True)


class OrderItem(Base):
    __tablename__ = "order_items"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uid)
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), index=True)
    shop_id: Mapped[str] = mapped_column(ForeignKey("shops.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[str] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), index=True)
    qty: Mapped[int] = mapped_column(Integer)
    unit_price_minor: Mapped[int] = mapped_column(BigInteger)
    buyer_delivery_minor: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    commission_rate_bp: Mapped[int | None] = mapped_column(Integer, nullable=True)
    returns: Mapped[list["ReturnEvent"]] = relationship(cascade="all, delete-orphan", passive_deletes=True)


class ReturnEvent(Base):
    __tablename__ = "return_events"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uid)
    item_id: Mapped[str] = mapped_column(ForeignKey("order_items.id", ondelete="CASCADE"), index=True)
    shop_id: Mapped[str] = mapped_column(ForeignKey("shops.id", ondelete="CASCADE"), index=True)
    returned_qty: Mapped[int] = mapped_column(Integer)
    confirmed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    refund_minor: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    commission_returned_minor: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    delivery_returned_minor: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    reverse_delivery_minor: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    goods_sellable: Mapped[bool | None] = mapped_column(Boolean, nullable=True)


class ExpenseEntry(Base):
    __tablename__ = "expense_entries"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uid)
    shop_id: Mapped[str] = mapped_column(ForeignKey("shops.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(16))  # ads | other
    amount_minor: Mapped[int] = mapped_column(BigInteger)
    period_start: Mapped[date] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date)
    source: Mapped[str] = mapped_column(String(16), default="manual")


class ProductStock(Base):
    """Остаток товара, внесённый продавцом вручную (склад, ТЗ/PROPOSALS пункт 18). Не меняет данные Kaspi."""
    __tablename__ = "product_stocks"
    __table_args__ = (UniqueConstraint("product_id", name="uq_product_stock_product"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uid)
    shop_id: Mapped[str] = mapped_column(ForeignKey("shops.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[str] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), index=True)
    qty: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    delisted: Mapped[bool] = mapped_column(Boolean, default=False)  # снят с продажи (XML) после подтверждения
    last_alert_level: Mapped[str | None] = mapped_column(String(8), nullable=True)  # последний отправленный порог


class StockMovement(Base):
    """Журнал движений склада (К-1 от 22.11): инвентаризация (остаток на момент) и приход. Дата — дата события, не ввода."""
    __tablename__ = "stock_movements"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uid)
    shop_id: Mapped[str] = mapped_column(ForeignKey("shops.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[str] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(16))  # inventory | receipt
    qty: Mapped[int] = mapped_column(Integer)
    example: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())  # К-33 А3: «пример»
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class ImportBatch(Base):
    __tablename__ = "import_batches"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uid)
    shop_id: Mapped[str] = mapped_column(ForeignKey("shops.id", ondelete="CASCADE"), index=True)
    filename: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(16), default="uploaded")  # uploaded|previewed|applied|undone
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    undone_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rows_total: Mapped[int] = mapped_column(Integer, default=0)
    # Разобранные строки и сопоставление колонок (JSON). Содержимое файла не хранится.
    payload: Mapped[str] = mapped_column(Text, default="{}")


class AIConversation(Base):
    __tablename__ = "ai_conversations"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uid)
    shop_id: Mapped[str] = mapped_column(ForeignKey("shops.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(120), default="Диалог")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    turns: Mapped[list["AITurn"]] = relationship(cascade="all, delete-orphan", passive_deletes=True)


class AITurn(Base):
    __tablename__ = "ai_turns"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uid)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("ai_conversations.id", ondelete="CASCADE"), index=True
    )
    shop_id: Mapped[str] = mapped_column(String(32), index=True)
    user_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)
    # Вопрос не логируется в ИИ-учёт, но нужен для истории; удаляется вместе с диалогом.
    question: Mapped[str] = mapped_column(Text)
    answer_json: Mapped[str] = mapped_column(Text)  # структурированный ответ


class AIFeedback(Base):
    __tablename__ = "ai_feedback"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uid)
    shop_id: Mapped[str] = mapped_column(String(32), index=True)
    turn_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    kind: Mapped[str] = mapped_column(String(16))  # up | down | flag
    reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Контекст для измерения качества на бете: вопрос с маскировкой (телефоны, почта, адреса), признак отказа
    question_masked: Mapped[str | None] = mapped_column(Text, nullable=True)
    refused: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    refusal_category: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class AIUsageEvent(Base):
    __tablename__ = "ai_usage_events"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uid)
    user_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    shop_id: Mapped[str] = mapped_column(String(32), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)
    model: Mapped[str] = mapped_column(String(64), default="mock")
    tool_calls: Mapped[int] = mapped_column(Integer, default=0)
    kind: Mapped[str] = mapped_column(String(16), default="question")  # question | draft (QA-04)
    cost_micro_usd: Mapped[int] = mapped_column(Integer, default=0)  # стоимость вызова, миллионные доли доллара (QA-03)


class ProductDraft(Base):
    __tablename__ = "product_drafts"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uid)
    shop_id: Mapped[str] = mapped_column(String(32), index=True)
    facts: Mapped[str] = mapped_column(Text)
    output_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class NotificationSettings(Base):
    __tablename__ = "notification_settings"
    user_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    product_in_minus: Mapped[bool] = mapped_column(Boolean, default=False)
    weekly_summary: Mapped[bool] = mapped_column(Boolean, default=False)
    quiet_hours: Mapped[bool] = mapped_column(Boolean, default=False)


class AuditEvent(Base):
    """Журнал чувствительных действий. Без персональных данных: только действие и идентификаторы."""
    __tablename__ = "audit_events"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uid)
    action: Mapped[str] = mapped_column(String(64))
    entity: Mapped[str] = mapped_column(String(64))
    result: Mapped[str] = mapped_column(String(16), default="ok")
    actor_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    shop_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class KaspiCatalog(Base):
    """Прайс-лист продавца, импортированный из кабинета Kaspi (К-16.3). Наш файл строится из него:
    товары и цены продавца сохраняются, меняются только наличие и остатки по складам."""
    __tablename__ = "kaspi_catalogs"
    shop_id: Mapped[str] = mapped_column(ForeignKey("shops.id", ondelete="CASCADE"), primary_key=True)
    xml_text: Mapped[str] = mapped_column(Text)
    offers_count: Mapped[int] = mapped_column(Integer)
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class KaspiConnection(Base):
    """Подключение магазина Kaspi (этап 2). Токен хранится только в зашифрованном виде (Fernet)."""
    __tablename__ = "kaspi_connections"
    shop_id: Mapped[str] = mapped_column(ForeignKey("shops.id", ondelete="CASCADE"), primary_key=True)
    seller_id: Mapped[str] = mapped_column(String(64))
    token_enc: Mapped[str] = mapped_column(Text)
    price_key: Mapped[str] = mapped_column(String(64))  # секрет в адресе прайс-листа; меняется при каждом подключении
    store_ids: Mapped[str | None] = mapped_column(Text, nullable=True)  # коды складов Kaspi через запятую (storeId из кабинета)
    store_hint: Mapped[str | None] = mapped_column(Text, nullable=True)  # подсказка кода склада из данных заказов (не значение)
    backfill_done: Mapped[bool] = mapped_column(Boolean, default=False)  # 90 дней догружены (К-18.3)
    backfill_page: Mapped[int] = mapped_column(Integer, default=0)  # страница догрузки, с которой продолжить
    load_done: Mapped[int] = mapped_column(Integer, default=0)  # сколько заказов загружено (прогресс)
    load_total: Mapped[int | None] = mapped_column(Integer, nullable=True)  # всего заказов за 90 дней (из ответа Kaspi)
    status: Mapped[str] = mapped_column(String(16), default="active")  # active | token_invalid
    cursor_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)  # время создания самого свежего обработанного заказа
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(200), nullable=True)
    connected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    # К-21: токен подключается один раз; новый токен того же магазина — только в окно, которое открыл владелец (24 ч)
    reconnect_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AIBudgetAlert(Base):
    """Оповещение владельцу о бюджете ИИ: один раз на уровень (warn 80%, exhausted 100%) в месяц (1.4)."""
    __tablename__ = "ai_budget_alerts"
    month: Mapped[str] = mapped_column(String(7), primary_key=True)  # YYYY-MM
    level: Mapped[str] = mapped_column(String(16), primary_key=True)  # warn | exhausted
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class AnalyticsDaily(Base):
    """Счётчики событий использования по дням (3.9). Без пользователей, устройств и адресов: только имя события и дата."""
    __tablename__ = "analytics_daily"
    day: Mapped[str] = mapped_column(String(10), primary_key=True)  # YYYY-MM-DD, UTC
    event: Mapped[str] = mapped_column(String(64), primary_key=True)
    count: Mapped[int] = mapped_column(Integer, default=0)


class OwnerAlertLog(Base):
    """Отметка отправленного оповещения владельцу (3.10): одно письмо на ключ (день, час или событие)."""
    __tablename__ = "owner_alert_log"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class AppErrorEvent(Base):
    """Каждое появление ошибки сервера (для правила всплеска, 3.10). Хранится 2 суток; без текста и адреса."""
    __tablename__ = "app_error_events"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uid)
    fingerprint: Mapped[str] = mapped_column(String(32), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)
