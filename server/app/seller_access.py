"""Номер продавца и особые условия доступа (К-21, решения владельца 23.11.2026, 01:39 и 01:53).

Номер продавца — 8 случайных цифр. Создаётся один раз, при первом успешном подключении магазина Kaspi, и навсегда
связан с магазином (ID продавца Kaspi, хранится только хешем с секретом сервера) и аккаунтом. В номере нет ни токена,
ни данных телефона: его можно называть в поддержке. Один магазин — один номер — один аккаунт.
После удаления аккаунта остаются только номер, хеш ID продавца и отметки «пробный период был» и «блокировка».

Особые условия (только владелец, только через админку): доступ без подписки на 1, 3 или 6 месяцев, досрочная отмена.
Привязка — к номеру продавца (то есть к магазину Kaspi), а не к почте. Доступ только бесплатный (OPERATIONS.md).
"""

from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import DateTime, String, select
from sqlalchemy.orm import Mapped, Session as DbSession, mapped_column

from .db import Base
from .errors import ApiError
from .timeutil import utc_now

RECONNECT_HOURS = 24
SPECIAL_MONTHS = {1: 30, 3: 91, 6: 182}  # дни: месяц считаем как 30 дней, 3 и 6 месяцев — по календарной длине


def _uid() -> str:
    return uuid.uuid4().hex


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


class SellerNumber(Base):
    __tablename__ = "seller_numbers"
    number: Mapped[str] = mapped_column(String(8), primary_key=True)
    seller_hash: Mapped[str] = mapped_column(String(64), unique=True)
    user_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)  # None — аккаунт удалён
    shop_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    blocked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class SpecialAccess(Base):
    """Доступ без подписки, выданный владельцем. Видит и даёт только владелец."""

    __tablename__ = "special_access"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uid)
    number: Mapped[str] = mapped_column(String(8), index=True)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    comment: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


def seller_hash(seller_id: str) -> str:
    from .billing import _hash

    return _hash("seller", seller_id.strip())


def by_seller(db: DbSession, seller_id: str) -> SellerNumber | None:
    return db.scalar(select(SellerNumber).where(SellerNumber.seller_hash == seller_hash(seller_id)))


def by_user(db: DbSession, user_id: str | None) -> SellerNumber | None:
    if not user_id:
        return None
    return db.scalar(select(SellerNumber).where(SellerNumber.user_id == user_id))


def for_shop(db: DbSession, shop_id: str) -> SellerNumber | None:
    return db.scalar(select(SellerNumber).where(SellerNumber.shop_id == shop_id))


def check_can_connect(db: DbSession, user_id: str | None, seller_id: str) -> None:
    """До обращения к Kaspi: магазин не занят другим аккаунтом, не заблокирован, аккаунт не привязан к другому магазину."""
    row = by_seller(db, seller_id)
    if row is not None and row.blocked_at is not None:
        raise ApiError(403, "account_blocked", "Этот магазин Kaspi заблокирован в Satti. Напишите в поддержку.")
    if row is not None and row.user_id not in (None, user_id):
        raise ApiError(409, "kaspi_shop_taken",
                       "Этот магазин Kaspi уже подключён к другому аккаунту Satti. Напишите в поддержку.")
    mine = by_user(db, user_id)
    if mine is not None and mine.seller_hash != seller_hash(seller_id):
        raise ApiError(409, "kaspi_other_shop",
                       "Аккаунт навсегда привязан к другому магазину Kaspi. Подключить другой магазин нельзя.")


def bind(db: DbSession, user_id: str | None, shop_id: str, seller_id: str) -> SellerNumber:
    """После успешного подключения: номер создаётся один раз; после удаления аккаунта — привязывается к новому."""
    row = by_seller(db, seller_id)
    if row is None:
        while True:
            number = str(10_000_000 + secrets.randbelow(90_000_000))  # 8 цифр, без ведущего нуля
            if db.get(SellerNumber, number) is None:
                break
        row = SellerNumber(number=number, seller_hash=seller_hash(seller_id))
        db.add(row)
    row.user_id, row.shop_id = user_id, shop_id
    db.flush()
    return row


def forget_account(db: DbSession, user_id: str) -> None:
    """Удаление аккаунта: остаются номер, хеш ID продавца и блокировка; особые условия удаляются."""
    from sqlalchemy import delete

    for row in db.scalars(select(SellerNumber).where(SellerNumber.user_id == user_id)).all():
        db.execute(delete(SpecialAccess).where(SpecialAccess.number == row.number))
        row.user_id, row.shop_id = None, None


def active_special(db: DbSession, shop_id: str, now: datetime | None = None) -> SpecialAccess | None:
    now = now or utc_now()
    row = for_shop(db, shop_id)
    if row is None:
        return None
    for sa in db.scalars(select(SpecialAccess).where(SpecialAccess.number == row.number,
                                                     SpecialAccess.cancelled_at.is_(None))).all():
        if _aware(sa.starts_at) <= now < _aware(sa.ends_at):
            return sa
    return None


def grant_special(db: DbSession, number: str, months: int, comment: str, now: datetime | None = None) -> SpecialAccess:
    if months not in SPECIAL_MONTHS:
        raise ApiError(422, "validation", "Срок — 1, 3 или 6 месяцев.")
    now = now or utc_now()
    for sa in db.scalars(select(SpecialAccess).where(SpecialAccess.number == number,
                                                     SpecialAccess.cancelled_at.is_(None))).all():
        if _aware(sa.ends_at) > now:
            sa.cancelled_at = now  # новый срок заменяет действующий
    sa = SpecialAccess(number=number, starts_at=now, ends_at=now + timedelta(days=SPECIAL_MONTHS[months]),
                       comment=comment.strip()[:500])
    db.add(sa)
    db.flush()
    return sa


def cancel_special(db: DbSession, number: str, now: datetime | None = None) -> int:
    now = now or utc_now()
    count = 0
    for sa in db.scalars(select(SpecialAccess).where(SpecialAccess.number == number,
                                                     SpecialAccess.cancelled_at.is_(None))).all():
        if _aware(sa.ends_at) > now:
            sa.cancelled_at = now
            count += 1
    return count


__all__ = ["SellerNumber", "SpecialAccess", "check_can_connect", "bind", "by_user", "for_shop", "active_special",
           "grant_special", "cancel_special", "forget_account", "RECONNECT_HOURS"]
