"""Отправка писем: коды входа и удаления, служебные письма о подписке и хранении, оповещения владельцу (3.6, 1.4).

- С SATTI_SMTP_HOST письма уходят через SMTP (STARTTLS по умолчанию, логин — если задан).
- Без него письма пишутся в папку outbox (SATTI_OUTBOX_DIR): разработка и тесты. В продакшене это проверяется при запуске.
- Ошибка отправки — MailError без адреса и текста письма. Журналы не содержат ни кодов, ни адресов (spec, раздел 13).
"""

from __future__ import annotations

import logging
import smtplib
import ssl
import uuid
from datetime import datetime, timezone
from email.message import EmailMessage

from .config import settings

log = logging.getLogger("satti.mail")


class MailError(Exception):
    """Письмо не отправлено. Сообщение не содержит адреса и текста."""


CODE_TEXT = {
    "ru": {
        "login": ("Код для входа в Satti Seller", "Ваш код: {code}\nКод действует {minutes} минут.\n"),
        "delete": ("Код для удаления аккаунта Satti Seller", "Ваш код: {code}\nКод действует {minutes} минут.\n"),
    },
    "kk": {  # перевод требует проверки носителем языка
        "login": ("Satti Seller-ге кіру коды", "Сіздің кодыңыз: {code}\nКод {minutes} минут бойы жарамды.\n"),
        "delete": ("Satti Seller аккаунтын жою коды", "Аккаунтты жоюға арналған кодыңыз: {code}\nКод {minutes} минут бойы жарамды.\n"),
    },
}


def _write_outbox(to_email: str, subject: str, text: str) -> None:
    settings.outbox_dir.mkdir(parents=True, exist_ok=True)
    body = f"To: {to_email}\nSubject: {subject}\n\n{text}\n"
    name = f"{datetime.now(timezone.utc):%Y%m%d%H%M%S}-{uuid.uuid4().hex[:8]}.eml"
    (settings.outbox_dir / name).write_text(body, encoding="utf-8")


def _deliver_smtp(to_email: str, subject: str, text: str) -> None:
    msg = EmailMessage()
    msg["From"] = settings.smtp_from
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.set_content(text)
    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=settings.smtp_timeout) as smtp:
            if settings.smtp_starttls:
                smtp.starttls(context=ssl.create_default_context())
            if settings.smtp_user:
                smtp.login(settings.smtp_user, settings.smtp_password)
            smtp.send_message(msg)
    except (smtplib.SMTPException, OSError) as exc:
        # без адреса и текста письма: только тип ошибки
        log.error("smtp delivery failed: %s", type(exc).__name__)
        raise MailError("почта недоступна") from exc


def _deliver(to_email: str, subject: str, text: str) -> None:
    if settings.smtp_host:
        _deliver_smtp(to_email, subject, text)
    else:
        _write_outbox(to_email, subject, text)


def _lang(lang: str | None) -> str:
    return "kk" if lang == "kk" else "ru"


def send_code_email(to_email: str, code: str, purpose: str = "login", lang: str | None = None) -> None:
    subject, template = CODE_TEXT[_lang(lang)][purpose if purpose in ("login", "delete") else "login"]
    text = template.format(code=code, minutes=settings.code_ttl_minutes)
    _deliver(to_email, subject, text)


def send_notice_email(to_email: str, subject: str, text: str) -> None:
    """Служебное письмо о подписке и хранении данных (ТЗ 2.1, 9.3). Тот же почтовый канал, что и коды."""
    _deliver(to_email, subject, text)


def send_owner_alert(subject: str, text: str) -> bool:
    """Оповещение владельцу (1.4). Без SATTI_OWNER_ALERT_EMAIL ничего не отправляется: возвращает False."""
    if not settings.owner_alert_email:
        log.warning("owner alert skipped: SATTI_OWNER_ALERT_EMAIL is not set")
        return False
    _deliver(settings.owner_alert_email, subject, text)
    return True
