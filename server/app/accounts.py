"""Удаление аккаунта: все записи, связанные с пользователем (AUD-08).

Используется и приложением (/me/deletion/confirm), и веб-формой (/delete-account/confirm) — одна реализация.
Остаются только отметки защиты пробного периода (BillingMark, только хеши): они нужны, чтобы пробный период
нельзя было взять повторно (ТЗ 2.1, 8.2). Персональных данных в них нет.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import Session as DbSession

from .admin import AdminTotp
from .billing import RetentionEvent, Subscription
from . import audit
from .models import AIConversation, AIFeedback, AITurn, AIUsageEvent, AuthCode, NotificationSettings, Session, Shop, User
from .social_auth import SocialIdentity


def delete_user_account(db: DbSession, user: User) -> None:
    from . import seller_access

    # К-21 (решение владельца 01:53): остаются номер продавца, хеш ID продавца, блокировка и отметки пробного периода
    seller_access.forget_account(db, user.id)
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
    # без идентификатора пользователя: после удаления он бы указывал в никуда
    audit.record(db, "account_delete", "user")


# ---------- деактивация на 30 дней (К-21, решения владельца 23.11.2026, 01:17 и 01:24) ----------

DEACTIVATION_DAYS = 30


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def is_deactivated(user: User | None) -> bool:
    return user is not None and user.deactivated_at is not None


def deactivated_shop_ids(db: DbSession) -> set[str]:
    """Магазины деактивированных аккаунтов: синхронизация Kaspi, письма и прочее фоновое для них не идут."""
    return set(db.scalars(select(Shop.id).join(User, User.id == Shop.owner_user_id)
                          .where(User.deactivated_at.is_not(None))).all())


def deactivate_user(db: DbSession, user: User, now: datetime) -> datetime:
    """Доступ к данным закрыт, фоновое остановлено, данные хранятся 30 дней, затем удаляются как при полном удалении."""
    from .mailer import MailError, send_notice_email

    if user.deactivated_at is None:
        user.deactivated_at = now
        user.delete_after = now + timedelta(days=DEACTIVATION_DAYS)
    db.commit()
    audit.record(db, "account_deactivate", "user", actor_id=user.id)
    day = _aware(user.delete_after).astimezone(timezone(timedelta(hours=5))).strftime("%d.%m.%Y")
    try:
        send_notice_email(user.email, "Аккаунт Satti деактивирован",
                          f"Аккаунт деактивирован. Данные хранятся до {day}, затем удалятся безвозвратно.\n"
                          "Восстановить аккаунт можно до этой даты только с оплаченной подпиской Satti.\n"
                          "Подписка в App Store или Google Play сама не отменяется — отменить её можно в настройках магазина.\n"
                          "Замените ссылку на прайс-лист в кабинете Kaspi: пока аккаунт деактивирован, Satti прайс не отдаёт.")
    except MailError:
        pass  # дата показана на экране; письмо — дополнительное
    return _aware(user.delete_after)


def reactivate_user(db: DbSession, user: User) -> None:
    user.deactivated_at = None
    user.delete_after = None
    db.commit()
    audit.record(db, "account_reactivate", "user", actor_id=user.id)


def purge_deactivated(db: DbSession, now: datetime) -> int:
    """Ежедневно: аккаунты, у которых истекли 30 дней деактивации, удаляются полностью (как вариант «удалить»)."""
    users = db.scalars(select(User).where(User.deactivated_at.is_not(None), User.delete_after <= now)).all()
    for user in users:
        delete_user_account(db, user)
    return len(users)
