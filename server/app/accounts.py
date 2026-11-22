"""Удаление аккаунта: все записи, связанные с пользователем (AUD-08).

Используется и приложением (/me/deletion/confirm), и веб-формой (/delete-account/confirm) — одна реализация.
Остаются только отметки защиты пробного периода (BillingMark, только хеши): они нужны, чтобы пробный период
нельзя было взять повторно (ТЗ 2.1, 8.2). Персональных данных в них нет.
"""

from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.orm import Session as DbSession

from .admin import AdminTotp
from .billing import RetentionEvent, Subscription
from .models import AIConversation, AIFeedback, AITurn, AIUsageEvent, AuthCode, NotificationSettings, Session, Shop, User
from .social_auth import SocialIdentity


def delete_user_account(db: DbSession, user: User) -> None:
    shop_ids = list(db.scalars(select(Shop.id).where(Shop.owner_user_id == user.id)).all())
    if shop_ids:
        # подписка и отметки хранения относятся к магазину; сами магазины и их данные удаляются каскадно
        db.execute(delete(Subscription).where(Subscription.shop_id.in_(shop_ids)))
        db.execute(delete(RetentionEvent).where(RetentionEvent.shop_id.in_(shop_ids)))
        db.execute(delete(AIFeedback).where(AIFeedback.shop_id.in_(shop_ids)))  # оценки и жалобы — сразу при удалении аккаунта (решение владельца 22.11)
        db.execute(delete(Shop).where(Shop.id.in_(shop_ids)))
    db.execute(delete(AIConversation).where(AIConversation.user_id == user.id))
    db.execute(delete(AITurn).where(AITurn.user_id == user.id))
    db.execute(delete(AIUsageEvent).where(AIUsageEvent.user_id == user.id))
    db.execute(delete(NotificationSettings).where(NotificationSettings.user_id == user.id))
    db.execute(delete(SocialIdentity).where(SocialIdentity.user_id == user.id))
    # коды входа и удаления хранятся с открытым email — удаляем по адресу и по идентификатору
    db.execute(delete(AuthCode).where((AuthCode.user_id == user.id) | (AuthCode.email == user.email)))
    db.execute(delete(AdminTotp).where(AdminTotp.user_id == user.id))
    db.execute(delete(Session).where(Session.user_id == user.id))
    db.execute(delete(User).where(User.id == user.id))
    db.commit()
