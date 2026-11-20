"""Отправка писем с кодами.

В разработке и тестах письмо записывается в папку outbox (SATTI_OUTBOX_DIR), а не в журнал.
Журналы сервера не содержат ни кодов, ни адресов (docs/spec.md, раздел 13).
Боевой провайдер подключается здесь же после выбора сервиса (docs/owner.md, раздел 6.3).
"""

import uuid
from datetime import datetime, timezone

from .config import settings


def send_code_email(to_email: str, code: str, purpose: str = "login") -> None:
    settings.outbox_dir.mkdir(parents=True, exist_ok=True)
    subject = "Код для входа в Satti Seller" if purpose == "login" else "Код для удаления аккаунта Satti Seller"
    body = f"To: {to_email}\nSubject: {subject}\n\nВаш код: {code}\nКод действует 10 минут.\n"
    name = f"{datetime.now(timezone.utc):%Y%m%d%H%M%S}-{uuid.uuid4().hex[:8]}.eml"
    (settings.outbox_dir / name).write_text(body, encoding="utf-8")


def send_notice_email(to_email: str, subject: str, text: str) -> None:
    """Служебное письмо о подписке и хранении данных (ТЗ 2.1, 9.3). Тот же почтовый канал, что и коды."""
    settings.outbox_dir.mkdir(parents=True, exist_ok=True)
    body = f"To: {to_email}\nSubject: {subject}\n\n{text}\n"
    name = f"{datetime.now(timezone.utc):%Y%m%d%H%M%S}-{uuid.uuid4().hex[:8]}.eml"
    (settings.outbox_dir / name).write_text(body, encoding="utf-8")
