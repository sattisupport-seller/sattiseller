"""Модель данных (docs/spec.md, раздел 10) — объём этапа A (демо) и заготовки для бета-этапа.

Деньги — BigInteger в тиынах. Ставки — в базисных пунктах. Даты — UTC.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

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
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def _uid() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(timezone.utc)


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
    source: Mapped[str] = mapped_column(String(32), default="manual")  # manual | import | demo
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
    __tablename__ = "audit_events"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uid)
    action: Mapped[str] = mapped_column(String(64))
    entity: Mapped[str] = mapped_column(String(64))
    result: Mapped[str] = mapped_column(String(16), default="ok")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
