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


def _revoke_apple_tokens(db: DbSession, user_id: str) -> None:
    from . import apple_tokens
    from .kaspi import KaspiAuthError, decrypt_token

    for link in db.scalars(select(SocialIdentity).where(SocialIdentity.user_id == user_id,
                                                        SocialIdentity.provider == "apple",
                                                        SocialIdentity.refresh_token_enc.is_not(None))).all():
        try:
            apple_tokens.revoke(decrypt_token(link.refresh_token_enc))
        except KaspiAuthError:
            # аудит 27.11, L5: ключ сменился без ротации — токен не отозвать; удаление продолжается, но громко
            import logging

            logging.getLogger("satti.apple").error("apple token revoke impossible: refresh token cannot be decrypted")


def delete_user_account(db: DbSession, user: User) -> None:
    from . import seller_access

    # К-21 (решение владельца 01:53): остаются номер продавца, хеш ID продавца, блокировка и отметки пробного периода
    seller_access.forget_account(db, user.id)
    _revoke_apple_tokens(db, user.id)  # 3.3: требование Apple — отозвать токены Sign in with Apple
    shop_ids = list(db.scalars(select(Shop.id).where(Shop.owner_user_id == user.id)).all())
    if shop_ids:
        # подписка и отметки хранения относятся к магазину; сами магазины и их данные удаляются каскадно
        db.execute(delete(Subscription).where(Subscription.shop_id.in_(shop_ids)))
        from .store_billing import StorePurchase  # аудит 27.11, L1: ключ покупки магазина — тоже данные аккаунта

        db.execute(delete(StorePurchase).where(StorePurchase.shop_id.in_(shop_ids)))
        db.execute(delete(RetentionEvent).where(RetentionEvent.shop_id.in_(shop_ids)))
        db.execute(delete(AIFeedback).where(AIFeedback.shop_id.in_(shop_ids)))  # оценки и жалобы — сразу при удалении аккаунта (решение владельца 22.11)
        db.execute(delete(Shop).where(Shop.id.in_(shop_ids)))
    db.execute(delete(AIConversation).where(AIConversation.user_id == user.id))
    db.execute(delete(AITurn).where(AITurn.user_id == user.id))
    db.execute(delete(AIUsageEvent).where(AIUsageEvent.user_id == user.id))
    db.execute(delete(NotificationSettings).where(NotificationSettings.user_id == user.id))
    from .push import DeviceToken, PushMessage  # 3.4: токены телефонов и очередь уведомлений

    db.execute(delete(DeviceToken).where(DeviceToken.user_id == user.id))
    db.execute(delete(PushMessage).where(PushMessage.user_id == user.id))
    db.execute(delete(SocialIdentity).where(SocialIdentity.user_id == user.id))
    # коды входа и удаления хранятся с открытым email — удаляем по адресу и по идентификатору
    db.execute(delete(AuthCode).where((AuthCode.user_id == user.id) | (AuthCode.email == user.email)))
    db.execute(delete(AdminTotp).where(AdminTotp.user_id == user.id))
    db.execute(delete(Session).where(Session.user_id == user.id))
    email = user.email
    db.execute(delete(User).where(User.id == user.id))
    db.commit()
    # без идентификатора пользователя: после удаления он бы указывал в никуда
    audit.record(db, "account_delete", "user")
    _send_deleted_letter(email)


def _send_deleted_letter(email: str) -> None:
    """3.6: подтверждение удаления. Адрес нигде не сохраняется — только письмо в почтовый сервис."""
    from .mailer import MailError, send_notice_email

    try:
        send_notice_email(email, "Аккаунт Satti удалён",
                          "Ваш аккаунт Satti и данные магазина удалены. Из резервных копий данные удалятся "
                          "не позже чем через 30 дней.\n"
                          "Подписка в App Store или Google Play сама не отменяется — "
                          "проверьте её в настройках магазина приложений.\n"
                          "Если вы не удаляли аккаунт, напишите в поддержку.")
    except MailError:
        pass  # удаление уже выполнено; письмо — подтверждение


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


def check_delete_code(db: DbSession, user: User, code: str) -> bool:
    """Код удаления или деактивации из письма (аудит 27.11, M1/M2): верный — True и код погашен.
    Неверный — атомарно +1 к попыткам; после settings.code_max_attempts код сгорает (нужен новый из письма)."""
    from sqlalchemy import update

    from .config import settings
    from .security import hash_code

    row = db.scalar(select(AuthCode).where(AuthCode.user_id == user.id, AuthCode.purpose == "delete",
                                           AuthCode.used.is_(False)).order_by(AuthCode.expires_at.desc()))
    if row is None or _aware(row.expires_at) < datetime.now(timezone.utc) or row.attempts >= settings.code_max_attempts:
        return False
    if hash_code(user.email, code.strip()) != row.code_hash:
        db.execute(update(AuthCode).where(AuthCode.id == row.id).values(attempts=AuthCode.attempts + 1))
        db.execute(update(AuthCode).where(AuthCode.id == row.id, AuthCode.attempts >= settings.code_max_attempts)
                   .values(used=True))
        db.commit()
        return False
    done = db.execute(update(AuthCode).where(AuthCode.id == row.id, AuthCode.used.is_(False))
                      .values(used=True)).rowcount  # два параллельных запроса с верным кодом — проходит один
    db.commit()
    return bool(done)
