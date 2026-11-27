"""Карточка товара через ИИ (К-14, решение владельца 22.11.2026, ADR 0011).

- Живая модель (та же, что у помощника) получает факты продавца и фото (если есть). Фото не сохраняются на сервере,
  но уходят в ИИ-сервис (согласие покупателя/продавца на это — в тексте согласия).
- Результат только на русском: 3 названия, описание, характеристики.
- Правила для модели и проверка кодом: только факты из текста продавца и то, что явно видно на фото; неизвестное —
  «Уточнить»; без контактов, ссылок, выдуманного бренда, «оригинала», «гарантии»; каждое число — из фактов.
  Ответ, который не проходит проверку, пересобирается по шаблону (app.ai.product_draft).
- Ошибка модели, исчерпанный бюджет, выключатель — шаблон с понятной пометкой (вызывающий код).
"""

from __future__ import annotations

import base64
import json
import logging
import re
from dataclasses import dataclass, field

import httpx

from .config import settings
from .privacy import contains_pii, mask_text

log = logging.getLogger(__name__)

MODEL_URL = "https://api.anthropic.com/v1/messages"
MAX_PHOTO_BYTES = 5 * 1024 * 1024
KK_LETTERS = set("әғқңөұүһі")
NUMBER = re.compile(r"\d+(?:[.,]\d+)?")
LINK = re.compile(r"https?://|www\.|@|\.(?:kz|com|ru|net|org)\b", re.I)
# слова, которые нельзя писать без фактов продавца (правило ADR 0011)
FORBIDDEN_CLAIMS = re.compile(r"оригинал|гарант|сертифицир|подлинн", re.I)

SYSTEM = (
    "Ты составляешь карточку товара для продавца маркетплейса Kaspi. Пиши только по-русски.\n"
    "Правила:\n"
    "1. Используй только факты, которые продавец написал в тексте, и то, что явно видно на фото.\n"
    "2. Не выдумывай характеристики, числа, бренд, материал, гарантию, «оригинал», комплектацию.\n"
    "3. Если сведения неизвестны — пиши значение «Уточнить».\n"
    "4. Никаких контактов, ссылок, адресов, телефонов, электронной почты.\n"
    "5. Каждое число в ответе должно быть в фактах продавца.\n"
    "Ответ — только JSON без пояснений, по схеме:\n"
    '{"titles": ["название 1", "название 2", "название 3"], '
    '"description": "описание в 2–4 предложениях", '
    '"characteristics": [{"name": "Материал", "value": "..."}, {"name": "Размеры", "value": "..."}, '
    '{"name": "Комплектация", "value": "..."}]}\n'
    "Каждое название — не длиннее 60 символов."
)


class DraftFallback(Exception):
    """Живой черновик не получен или не прошёл проверку: вызывающий код отдаёт шаблон."""


@dataclass
class LiveResult:
    draft: dict
    tin: int = 0
    tout: int = 0
    tcw: int = 0
    tcr: int = 0
    photos_sent: int = 0
    notes: list[str] = field(default_factory=list)


def _mime(head: bytes) -> str | None:
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if head.startswith(b"\x89PNG"):
        return "image/png"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    return None


def _image_blocks(photos: list[bytes]) -> list[dict]:
    blocks = []
    for data in photos:
        mime = _mime(data[:16])
        if mime is None or len(data) > MAX_PHOTO_BYTES:
            continue  # такие фото проверяет вызывающий код; здесь — молча пропускаем
        blocks.append({"type": "image", "source": {"type": "base64", "media_type": mime,
                                                   "data": base64.b64encode(data).decode("ascii")}})
    return blocks


SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


def _allowed_numbers(facts: str) -> set[str]:
    return {n.replace(",", ".") for n in NUMBER.findall(facts)}


def _extract_json(text: str) -> dict:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise DraftFallback("модель вернула не JSON")
    try:
        obj = json.loads(m.group(0))
    except ValueError as exc:
        raise DraftFallback("JSON не разобран") from exc
    if not isinstance(obj, dict):
        raise DraftFallback("ответ не объект")
    return obj


def check_draft(obj: dict, facts: str) -> dict:
    """Проверка кодом. Возвращает очищенный черновик или бросает DraftFallback."""
    titles = obj.get("titles")
    if not isinstance(titles, list) or len(titles) != 3 or not all(isinstance(t, str) and t.strip() for t in titles):
        raise DraftFallback("нет трёх названий")
    titles = [t.strip() for t in titles]
    if any(len(t) > 60 for t in titles):
        raise DraftFallback("название длиннее 60 знаков")
    description = obj.get("description")
    if not isinstance(description, str) or not description.strip() or len(description) > 1500:
        raise DraftFallback("описание пустое или слишком длинное")
    raw_chars = obj.get("characteristics")
    if not isinstance(raw_chars, list) or not raw_chars or len(raw_chars) > 20:
        raise DraftFallback("нет характеристик")
    allowed = _allowed_numbers(facts)

    def _has_unknown_number(text: str) -> bool:
        return any(n.replace(",", ".") not in allowed for n in NUMBER.findall(text))

    chars = []
    for row in raw_chars:
        if not isinstance(row, dict) or not isinstance(row.get("name"), str) or not isinstance(row.get("value"), str):
            raise DraftFallback("характеристика не в формате name/value")
        value = row["value"].strip()[:200] or "Уточнить"
        # К-20 п.3: число в характеристике, которого нет в фактах (например, снято с фото), не отдаёт
        # весь ответ в шаблон: такое значение становится «Уточнить».
        if _has_unknown_number(value):
            value = "Уточнить"
        chars.append({"name": row["name"].strip()[:60], "value": value})

    # К-22 п.4 (решение координатора): число, которого нет в фактах, не отдаёт весь ответ в шаблон.
    # В описании убираем только предложение с этим числом; название с таким числом берём из шаблона.
    # Шаблон целиком — только если ответ не разобран или после проверки пуст.
    sentences = [x for x in SENTENCE_SPLIT.split(description.strip()) if x.strip()]
    kept = [x for x in sentences if not _has_unknown_number(x)]
    if not kept:
        raise DraftFallback("описание пустое после проверки чисел")
    description = " ".join(kept)
    if any(_has_unknown_number(t) for t in titles):
        from .ai import product_draft  # отложенный импорт: ai.py большой и тянет отчёты

        template = product_draft(facts, "ru", 0)["titles"]
        titles = [template[i % len(template)] if _has_unknown_number(t) else t for i, t in enumerate(titles)]

    everything = " ".join([*titles, description, *(c["name"] + " " + c["value"] for c in chars)])
    if LINK.search(everything) or contains_pii(everything):
        raise DraftFallback("контакты или ссылки в ответе")
    lowered_facts = facts.lower()
    for claim in FORBIDDEN_CLAIMS.findall(everything):
        if claim.lower() not in lowered_facts:
            raise DraftFallback("выдуманное утверждение (оригинал, гарантия)")
    if any(ch in KK_LETTERS for ch in everything.lower()):
        raise DraftFallback("ответ не на русском")
    return {"titles": titles, "description": description.strip(), "characteristics": chars}


def live_draft(facts: str, photos: list[bytes], transport=None) -> LiveResult:
    """Вызов модели. Факты маскируются до отправки. Бросает DraftFallback при любой проблеме."""
    if not settings.anthropic_api_key:
        raise DraftFallback("нет ключа")
    masked = mask_text(facts)
    blocks = _image_blocks(photos)
    content: list[dict] = [*blocks, {"type": "text", "text": f"Факты продавца:\n{masked}\n\nФото приложены выше, если есть."}]
    body = {"model": settings.ai_model, "max_tokens": 1200, "system": SYSTEM,
            "messages": [{"role": "user", "content": content}]}
    try:
        with httpx.Client(timeout=60.0, transport=transport) as http:
            resp = http.post(MODEL_URL, json=body, headers={
                "x-api-key": settings.anthropic_api_key, "anthropic-version": "2023-06-01",
                "content-type": "application/json"})
    except httpx.HTTPError as exc:
        raise DraftFallback(f"сеть: {type(exc).__name__}") from exc
    if resp.status_code >= 400:
        log.warning("draft provider error %s", resp.status_code)  # без текста фактов
        raise DraftFallback(f"ошибка модели {resp.status_code}")
    data = resp.json()
    text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
    usage = data.get("usage", {})
    draft = check_draft(_extract_json(text), masked)
    return LiveResult(draft=draft, tin=int(usage.get("input_tokens", 0)), tout=int(usage.get("output_tokens", 0)),
                      tcw=int(usage.get("cache_creation_input_tokens", 0) or 0),
                      tcr=int(usage.get("cache_read_input_tokens", 0) or 0), photos_sent=len(blocks))
