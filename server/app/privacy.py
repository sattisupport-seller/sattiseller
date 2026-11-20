"""Маскировка данных покупателей перед ИИ и в его журнале (ADR-0004).

Правило: Anthropic видит данные магазина, но не имена, телефоны, email и адреса покупателей.
Маскировка применяется к тексту вопроса и черновиков до отправки в модель и до записи в журнал диалогов.
Поля заказа, которые относятся к покупателю, маскируются по имени поля, даже если их значение — не текст из вопроса.

Ограничение: имена в свободном тексте без признаков (нет «имя:», нет отчества) распознаются плохо.
Поэтому имена покупателей в ИИ не передаются вовсе: в данных магазина их нет (см. ADR-0004, Kaspi не подключён).
"""

from __future__ import annotations

import re
from typing import Any

MASK_PHONE = "[телефон]"
MASK_EMAIL = "[email]"
MASK_ADDRESS = "[адрес]"
MASK_FIELD = "[скрыто]"

# Поля покупателя по имени (заказы Kaspi, импорт, будущие API)
BUYER_KEYS = {
    "buyer", "buyer_name", "buyer_phone", "buyer_email", "buyer_address", "customer", "customer_name",
    "customer_phone", "customer_email", "customer_address", "address", "phone", "email", "fio",
    "recipient", "recipient_name", "recipient_phone", "recipient_address",
}

# Телефоны: +7 / 8 / 7 и обычные форматы; 10–11 цифр с разделителями
PHONE_RE = re.compile(
    r"(?<!\w)(?:\+?\s?[78][\s\-.()]*)?\(?\d{3}\)?[\s\-.]*\d{3}[\s\-.]*\d{2}[\s\-.]*\d{2}(?!\w)"
    r"|(?<!\w)\+\d[\d\s\-.()]{8,}\d(?!\w)"
)
EMAIL_RE = re.compile(r"[\w.+\-]+@[\w\-]+(?:\.[\w\-]+)+")
# Адрес: ключевое слово улицы/дома и текст до конца фразы
ADDRESS_RE = re.compile(
    r"(?i)\b(?:ул\.|улица|пр\.|проспект|пер\.|переулок|мкр\.|микрорайон|дом|д\.|кв\.|квартира|"
    r"көш\.|даңғыл|үй)(?=[\s.,\d])\s*[^\n,.;!?]{0,60}(?:\d+[^\n,.;!?]{0,20})?"
)
# Признаки PII для предупреждений (без замены)
_PII_RE = (PHONE_RE, EMAIL_RE, ADDRESS_RE)


def contains_pii(text: str | None) -> bool:
    if not text:
        return False
    return any(rx.search(text) for rx in _PII_RE)


def mask_text(text: str | None) -> str:
    """Заменяет телефоны, email и адреса в тексте. Остальной текст не меняется."""
    if not text:
        return text or ""
    out = EMAIL_RE.sub(MASK_EMAIL, text)
    out = PHONE_RE.sub(MASK_PHONE, out)
    out = ADDRESS_RE.sub(MASK_ADDRESS, out)
    return out


def mask_value(key: str | None, value: Any) -> Any:
    """Значение поля: по имени поля покупателя — скрываем целиком, иначе маскируем текст."""
    if key is not None and key.lower() in BUYER_KEYS:
        return MASK_FIELD
    if isinstance(value, str):
        return mask_text(value)
    if isinstance(value, dict):
        return mask_obj(value)
    if isinstance(value, (list, tuple)):
        return [mask_value(None, v) for v in value]
    return value


def mask_obj(obj: dict) -> dict:
    """Рекурсивная маскировка словаря перед отправкой в ИИ или записью в журнал."""
    return {k: mask_value(k, v) for k, v in obj.items()}
