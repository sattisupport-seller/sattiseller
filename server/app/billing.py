"""Подписка, пробный период и хранение данных (ТЗ 2.1, разделы 8.2, 8.6, 9.1–9.3).

Состояние подписки хранит и проверяет только сервер. Отметки о пробном периоде — только хеши (3 года).
Проверка покупок через App Store и Google Play здесь не реализована: нужны аккаунты владельца (spec-2.1, 19.3, 19.10).
Блокировка включается флагом SATTI_BILLING_ENFORCED; без него приложение работает как в версии 2.0.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import DateTime, Integer, String, delete, select
from sqlalchemy.orm import Mapped, Session as DbSession, mapped_column

from .config import settings
from .db import Base
from .errors import ApiError
from . import reportcache
from .mailer import send_notice_email
from .models import (
    AIConversation,
    AIFeedback,
    AITurn,
    CommissionPreset,
    ExpenseEntry,
    ImportBatch,
    Order,
    OrderItem,
    Product,
    ProductCostVersion,
    ProductDraft,
    ReturnEvent,
    Shop,
    TaxRate,
    User,
)

TRIAL_DAYS = 14
RETENTION_DAYS = 90
ACCESS_STATES = {"trial", "active", "cancelled", "grace"}
NOTICE_DAYS = {"letter_0": 0, "letter_60": 60, "letter_83": 83}  # письма (9.3); удаление — на 90-й день


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _uid() -> str:
    return uuid.uuid4().hex


def _aware(dt: datetime | None) -> datetime | None:
    """SQLite отдаёт даты без часового пояса: считаем их UTC."""
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


class Subscription(Base):
    """Подписка магазина. Одна подписка — один магазин (ТЗ 2.1, раздел 1)."""

    __tablename__ = "subscriptions"
    shop_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    state: Mapped[str] = mapped_column(String(16))  # trial|active|cancelled|grace|on_hold|expired|revoked|refunded
    access_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    trial_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    store: Mapped[str] = mapped_column(String(16), default="none")  # apple | google | test | none
    lapsed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class BillingMark(Base):
    """Отметка защиты пробного периода: только хеш (аккаунт, телефон, магазин Kaspi). Хранится 3 года."""

    __tablename__ = "billing_marks"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uid)
    kind: Mapped[str] = mapped_column(String(16))  # user | device | shop
    key_hash: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class RetentionEvent(Base):
    """Какие письма о хранении уже отправлены магазину (каждое — один раз за период без подписки)."""

    __tablename__ = "retention_events"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uid)
    shop_id: Mapped[str] = mapped_column(String(32), index=True)
    kind: Mapped[str] = mapped_column(String(16))  # letter_0 | letter_60 | letter_83 | deleted
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


def _hash(kind: str, value: str) -> str:
    return hashlib.sha256(f"{settings.billing_pepper}|{kind}|{value}".encode("utf-8")).hexdigest()


def get_subscription(db: DbSession, shop_id: str) -> Subscription | None:
    return db.get(Subscription, shop_id)


def has_access(sub: Subscription | None, now: datetime) -> bool:
    if sub is None or sub.state not in ACCESS_STATES or sub.access_until is None:
        return False
    return now < _aware(sub.access_until)


def effective_state(sub: Subscription | None, now: datetime) -> str:
    """Состояние для экрана: none — подписки не было; expired — доступ закончился."""
    if sub is None:
        return "none"
    if has_access(sub, now):
        return sub.state
    return "expired"


def trial_eligible(db: DbSession, account_key: str | None, kaspi_key_id: str | None) -> bool:
    """Отметки защиты пробного периода (ТЗ 2.1, 8.2, решение владельца 20.11.2026).

    Телефон не используется: входа по телефону нет, а идентификатор устройства из заголовка клиент может подменить.
    Постоянный идентификатор телефона даст DeviceCheck (iOS) и Android ID — нужны нативные модули, задача 21.
    Отметка магазина появится при подключении Kaspi (задача 34): до этого магазин не проверяется.
    """
    checks = [("user", account_key), ("shop", kaspi_key_id)]
    # account_key — нормализованный email; хеш с секретом сервера (BillingMark.key_hash)
    for kind, value in checks:
        if not value:
            continue
        if db.scalar(select(BillingMark.id).where(BillingMark.kind == kind,
                                                  BillingMark.key_hash == _hash(kind, value))) is not None:
            return False
    return True


def start_trial(db: DbSession, shop: Shop, account_key: str | None, kaspi_key_id: str | None,
                now: datetime | None = None) -> Subscription:
    """Пробный период 14 дней. account_key — нормализованный email аккаунта. Отметки ставятся сразу."""
    now = now or _now()
    if get_subscription(db, shop.id) is not None:
        raise ApiError(409, "trial_used", "Подписка для этого магазина уже была.")
    if not trial_eligible(db, account_key, kaspi_key_id):
        raise ApiError(409, "trial_used", "Пробный период уже использован для этого аккаунта или магазина.")
    sub = Subscription(shop_id=shop.id, state="trial", access_until=now + timedelta(days=TRIAL_DAYS),
                       trial_started_at=now, store="test" if settings.billing_test_mode else "none")
    db.add(sub)
    for kind, value in (("user", account_key), ("shop", kaspi_key_id)):
        if value:
            db.add(BillingMark(kind=kind, key_hash=_hash(kind, value)))
    db.commit()
    return sub


def activate_paid(db: DbSession, shop: Shop, until: datetime, store: str, now: datetime | None = None) -> Subscription:
    """Оплаченный период: доступ возвращается; письма и отсчёт хранения сбрасываются, если данные ещё не удалены."""
    sub = get_subscription(db, shop.id) or Subscription(shop_id=shop.id, state="active")
    sub.state = "active"
    sub.access_until = until
    sub.store = store
    sub.lapsed_at = None
    db.add(sub)
    if sub.deleted_at is None:
        db.execute(delete(RetentionEvent).where(RetentionEvent.shop_id == shop.id))
    db.commit()
    return sub


def guard(db: DbSession, shop: Shop, now: datetime | None = None) -> None:
    """Блокировка данных магазина (ТЗ 2.1, 9.1). Демо и выключенный флаг — без проверок."""
    if not settings.billing_enforced or shop.is_demo:
        return
    if not has_access(get_subscription(db, shop.id), now or _now()):
        raise ApiError(403, "subscription_required", "Подписка закончилась. Оформите подписку, чтобы продолжить работу.")


def mark_lapsed(db: DbSession, now: datetime | None = None) -> int:
    """Фиксирует момент окончания доступа: от него считаются 90 дней хранения."""
    now = now or _now()
    count = 0
    for sub in db.scalars(select(Subscription).where(Subscription.lapsed_at.is_(None),
                                                     Subscription.deleted_at.is_(None))).all():
        if not has_access(sub, now):
            sub.lapsed_at = _aware(sub.access_until) or now
            count += 1
    db.commit()
    return count


def delete_shop_data(db: DbSession, shop_id: str) -> None:
    """Удаление данных магазина на 90-й день (ТЗ 2.1, 9.3). Аккаунт и подписка остаются."""
    db.execute(delete(ReturnEvent).where(ReturnEvent.shop_id == shop_id))
    db.execute(delete(OrderItem).where(OrderItem.shop_id == shop_id))
    db.execute(delete(Order).where(Order.shop_id == shop_id))
    db.execute(delete(ProductCostVersion).where(ProductCostVersion.shop_id == shop_id))
    db.execute(delete(Product).where(Product.shop_id == shop_id))
    db.execute(delete(CommissionPreset).where(CommissionPreset.shop_id == shop_id))
    db.execute(delete(ExpenseEntry).where(ExpenseEntry.shop_id == shop_id))
    db.execute(delete(TaxRate).where(TaxRate.shop_id == shop_id))
    db.execute(delete(ImportBatch).where(ImportBatch.shop_id == shop_id))
    db.execute(delete(AITurn).where(AITurn.shop_id == shop_id))
    db.execute(delete(AIConversation).where(AIConversation.shop_id == shop_id))
    db.execute(delete(AIFeedback).where(AIFeedback.shop_id == shop_id))
    db.execute(delete(ProductDraft).where(ProductDraft.shop_id == shop_id))
    sub = get_subscription(db, shop_id)
    if sub is not None:
        sub.deleted_at = _now()
    db.commit()
    reportcache.invalidate(shop_id)  # AUD-12: отчёты удалённого магазина больше не отдаём из кэша


def _letter_text(kind: str, lapsed_at: datetime) -> tuple[str, str]:
    delete_on = (_aware(lapsed_at) + timedelta(days=RETENTION_DAYS)).date()
    if kind == "letter_0":
        return ("Подписка закончилась — данные сохранены",
                f"Ваши данные магазина сохранены до {delete_on:%d.%m.%Y}. Оформите подписку, чтобы продолжить работу.")
    if kind == "letter_60":
        return ("Через 30 дней данные магазина будут удалены",
                "Оформите подписку, чтобы сохранить данные магазина.")
    if kind == "letter_83":
        return ("Через 7 дней данные магазина будут удалены",
                "Оформите подписку до удаления, чтобы сохранить данные магазина.")
    return ("Данные магазина удалены",
            "Срок хранения данных без подписки закончился. Аккаунт сохранён: можно оформить подписку заново.")


def _owner_email(db: DbSession, shop: Shop) -> str | None:
    if shop.owner_user_id is None:
        return None
    user = db.get(User, shop.owner_user_id)
    return user.email if user else None


def run_retention(db: DbSession, now: datetime | None = None) -> list[tuple[str, str]]:
    """Ежедневная задача (ТЗ 2.1, 9.3): письма на 0, 60, 83 день и удаление на 90-й. Возвращает сделанное."""
    now = now or _now()
    mark_lapsed(db, now)
    done: list[tuple[str, str]] = []
    subs = db.scalars(select(Subscription).where(Subscription.lapsed_at.is_not(None),
                                                 Subscription.deleted_at.is_(None))).all()
    for sub in subs:
        if has_access(sub, now):
            continue
        shop = db.get(Shop, sub.shop_id)
        if shop is None or shop.is_demo:
            continue
        days = (now - _aware(sub.lapsed_at)).days
        sent = set(db.scalars(select(RetentionEvent.kind).where(RetentionEvent.shop_id == shop.id)).all())
        for kind, threshold in NOTICE_DAYS.items():
            if days >= threshold and kind not in sent:
                _notify(db, shop, sub, kind, now)
                done.append((shop.id, kind))
        if days >= RETENTION_DAYS and "deleted" not in sent:
            delete_shop_data(db, shop.id)
            _notify(db, shop, sub, "deleted", now)
            done.append((shop.id, "deleted"))
    return done


def _notify(db: DbSession, shop: Shop, sub: Subscription, kind: str, now: datetime) -> None:
    email = _owner_email(db, shop)
    if email:
        subject, text = _letter_text(kind, sub.lapsed_at)
        send_notice_email(email, subject, text)
    db.add(RetentionEvent(shop_id=shop.id, kind=kind, created_at=now))
    db.commit()


def subscription_view(db: DbSession, shop: Shop, now: datetime | None = None) -> dict:
    now = now or _now()
    sub = get_subscription(db, shop.id)
    return {
        "state": effective_state(sub, now),
        "access_until": _aware(sub.access_until).isoformat() if sub and sub.access_until else None,
        "store": sub.store if sub else "none",
        "price_text": settings.subscription_price_text,
        "trial_days": TRIAL_DAYS,
        "data_delete_on": ((_aware(sub.lapsed_at) + timedelta(days=RETENTION_DAYS)).date().isoformat()
                           if sub and sub.lapsed_at else None),
    }


__all__ = ["guard", "start_trial", "activate_paid", "run_retention", "mark_lapsed", "subscription_view",
           "effective_state", "trial_eligible", "has_access"]
