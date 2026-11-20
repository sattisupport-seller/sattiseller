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
def contains_pii(text: str | None) -> bool:
    if not text:
        return False
    return any(rx.search(text) for rx in _PII_RE)


MASK_CARD = "[карта]"
MASK_IIN = "[ИИН]"
# AUD-19: номер банковской карты — 13–19 цифр (возможны пробелы и дефисы); маскируем только если проходит проверку Луна,
# чтобы не портить номера заказов и суммы
CARD_RE = re.compile(r"(?<![\d\w])(?:\d[ \-]?){12,18}\d(?![\d\w])")
# ИИН (Казахстан) — ровно 12 цифр подряд
IIN_RE = re.compile(r"(?<!\d)\d{12}(?!\d)")
# Признаки PII для предупреждений (без замены)
_PII_RE = (PHONE_RE, EMAIL_RE, ADDRESS_RE, IIN_RE)


def _luhn_ok(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def _mask_card(match: re.Match) -> str:
    digits = re.sub(r"\D", "", match.group(0))
    if 13 <= len(digits) <= 19 and _luhn_ok(digits):
        return MASK_CARD
    return match.group(0)


def mask_text(text: str | None) -> str:
    """Заменяет телефоны, email, адреса, номера карт и ИИН в тексте. Остальной текст не меняется."""
    if not text:
        return text or ""
    out = EMAIL_RE.sub(MASK_EMAIL, text)
    out = CARD_RE.sub(_mask_card, out)
    out = IIN_RE.sub(MASK_IIN, out)
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


# ---------- точные совпадения из данных заказов (ADR-0004, задача 3) ----------

MASK_BUYER = "[покупатель]"
BUYER_ATTRS = ("buyer_name", "buyer_address", "buyer_phone", "buyer_email")


def _phone_variants(value: str) -> set[str]:
    """Варианты записи телефона: только цифры, последние 10 цифр, с 8 и с +7."""
    digits = re.sub(r"\D", "", value)
    if len(digits) < 10:
        return set()
    last10 = digits[-10:]
    return {last10, "8" + last10, "7" + last10, "+7" + last10}


def buyer_values(orders) -> list[str]:
    """Имена, адреса, телефоны и email покупателей из заказов. Поля появятся с подключением Kaspi."""
    values: set[str] = set()
    for order in orders:
        for attr in BUYER_ATTRS:
            raw = getattr(order, attr, None)
            if not raw or not str(raw).strip():
                continue
            raw = str(raw).strip()
            if attr == "buyer_phone":
                values |= _phone_variants(raw)
            else:
                values.add(raw)
    return sorted(values, key=len, reverse=True)


def mask_known(text: str, values) -> str:
    """Заменяет точные совпадения со значениями заказов (без учёта регистра), длинные — первыми."""
    out = text
    for value in sorted({v for v in values if v and len(v) >= 3}, key=len, reverse=True):
        out = re.sub(re.escape(value), MASK_BUYER, out, flags=re.IGNORECASE)
    return out


def buyer_values_for_shop(db, shop_id: str) -> list[str]:
    from sqlalchemy import select

    from .models import Order

    return buyer_values(db.scalars(select(Order).where(Order.shop_id == shop_id)).all())
