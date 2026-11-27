"""Карточка товара через ИИ (К-14, ADR 0011): проверка кодом, вызов модели с фото, учёт стоимости, шаблон как запасной путь."""

import json

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app import api as api_module
from app import draft_ai
from app.config import settings
from app.db import engine
from app.errors import ApiError
from app.models import AIUsageEvent

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64
JPG = b"\xff\xd8\xff" + b"0" * 64
FACTS = "Термокружка стальная, двойные стенки, объём 450 мл, крышка-непроливайка"


def _good(**over) -> dict:
    base = {
        "titles": ["Термокружка стальная 450 мл", "Термокружка с крышкой-непроливайкой 450 мл", "Термокружка для кофе и чая"],
        "description": "Термокружка из нержавеющей стали с двойными стенками. Объём 450 мл. Крышка-непроливайка.",
        "characteristics": [{"name": "Материал", "value": "нержавеющая сталь"},
                            {"name": "Объём", "value": "450 мл"},
                            {"name": "Размеры", "value": "Уточнить"}],
    }
    base.update(over)
    return base


# ---------- проверка кодом ----------

def test_check_accepts_clean_output():
    out = draft_ai.check_draft(_good(), FACTS)
    assert len(out["titles"]) == 3 and out["characteristics"][1]["value"] == "450 мл"


def test_unknown_number_in_description_removes_only_that_sentence():
    # К-22 п.4: предложение с числом не из фактов убирается, остальная карточка остаётся
    out = draft_ai.check_draft(_good(description="Термокружка с двойными стенками. Вес 300 г. Объём 450 мл."), FACTS)
    assert out["description"] == "Термокружка с двойными стенками. Объём 450 мл."
    assert out["titles"][0] == "Термокружка стальная 450 мл"


def test_description_with_only_unknown_numbers_goes_to_template():
    with pytest.raises(draft_ai.DraftFallback, match="чисел"):
        draft_ai.check_draft(_good(description="Объём 450 мл, вес 300 г."), FACTS)


def test_unknown_number_in_title_takes_template_title():
    # К-22 п.4: название с числом не из фактов заменяется названием из шаблона, остальное — от модели
    titles = ["Термокружка стальная 500 мл", "Термокружка с крышкой-непроливайкой 450 мл", "Термокружка для кофе и чая"]
    out = draft_ai.check_draft(_good(titles=titles), FACTS)
    assert "500" not in out["titles"][0] and out["titles"][0].startswith("Термокружка")
    assert out["titles"][1:] == titles[1:]
    assert out["description"].startswith("Термокружка из нержавеющей стали")


def test_unknown_number_in_characteristic_becomes_clarify_not_template():
    # К-20 п.3: вес взят с фото, в фактах его нет — характеристика «Уточнить», остальной ответ сохраняется
    out = draft_ai.check_draft(_good(characteristics=[{"name": "Вес", "value": "300 г"},
                                                       {"name": "Объём", "value": "450 мл"}]), FACTS)
    assert out["characteristics"][0]["value"] == "Уточнить"
    assert out["characteristics"][1]["value"] == "450 мл"
    assert len(out["titles"]) == 3


def test_check_rejects_links_and_contacts():
    with pytest.raises(draft_ai.DraftFallback):
        draft_ai.check_draft(_good(description="Подробнее на www.shop-example.kz"), FACTS)
    with pytest.raises(draft_ai.DraftFallback):
        draft_ai.check_draft(_good(description="Пишите на seller@example.invalid"), FACTS)
    with pytest.raises(draft_ai.DraftFallback):
        draft_ai.check_draft(_good(description="Звоните +7 777 123 45 67"), FACTS)


def test_check_rejects_invented_guarantee_and_originality():
    # без чисел: число проверяется раньше, и здесь проверяем именно утверждения
    with pytest.raises(draft_ai.DraftFallback, match="выдуманное"):
        draft_ai.check_draft(_good(description="Оригинал, гарантия продавца."), FACTS)


def test_check_accepts_claim_that_is_in_facts():
    facts = FACTS + ". Оригинал, гарантия продавца"
    draft_ai.check_draft(_good(description="Оригинал, гарантия продавца."), facts)


def test_check_rejects_kazakh_text_and_wrong_shape():
    with pytest.raises(draft_ai.DraftFallback, match="русском"):
        draft_ai.check_draft(_good(description="Бұл термокружка, нержавеющая болат"), FACTS)
    with pytest.raises(draft_ai.DraftFallback, match="трёх названий"):
        draft_ai.check_draft(_good(titles=["одно", "два"]), FACTS)
    with pytest.raises(draft_ai.DraftFallback, match="60"):
        draft_ai.check_draft(_good(titles=["а" * 61, "б", "в"]), FACTS)


def test_extract_json_handles_surrounding_text():
    assert draft_ai._extract_json('Вот ответ: {"a": 1} спасибо')["a"] == 1
    with pytest.raises(draft_ai.DraftFallback):
        draft_ai._extract_json("без json")


# ---------- вызов модели ----------

def test_live_draft_sends_photo_and_masked_facts(monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", "sk-test-not-real")
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        seen["key"] = request.headers.get("x-api-key")
        text = json.dumps(_good(), ensure_ascii=False)
        return httpx.Response(200, json={"content": [{"type": "text", "text": text}],
                                         "usage": {"input_tokens": 900, "output_tokens": 200}})

    facts = FACTS + ", телефон продавца +77771234567"
    res = draft_ai.live_draft(facts, [PNG, JPG], transport=httpx.MockTransport(handler))
    content = seen["body"]["messages"][0]["content"]
    images = [b for b in content if b["type"] == "image"]
    assert len(images) == 2 and images[0]["source"]["media_type"] == "image/png"
    text_part = next(b["text"] for b in content if b["type"] == "text")
    assert "77771234567" not in json.dumps(seen["body"], ensure_ascii=False)  # контакт не уходит в модель
    assert "Термокружка" in text_part
    assert res.photos_sent == 2 and res.tin == 900 and res.tout == 200
    assert seen["body"]["model"] == settings.ai_model


def test_live_draft_falls_back_on_provider_error_and_bad_json(monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", "sk-test-not-real")
    err = httpx.MockTransport(lambda r: httpx.Response(529, json={"error": "overloaded"}))
    with pytest.raises(draft_ai.DraftFallback):
        draft_ai.live_draft(FACTS, [], transport=err)
    bad = httpx.MockTransport(lambda r: httpx.Response(200, json={"content": [{"type": "text", "text": "не json"}],
                                                                  "usage": {}}))
    with pytest.raises(draft_ai.DraftFallback):
        draft_ai.live_draft(FACTS, [], transport=bad)


# ---------- эндпоинт ----------

@pytest.fixture
def live_on(monkeypatch):
    monkeypatch.setattr(settings, "ai_live", True)
    monkeypatch.setattr(settings, "anthropic_api_key", "sk-test-not-real")


def _draft(client, demo, facts=FACTS, files=None):
    return client.post("/v1/ai/product-drafts", headers=demo["headers"],
                       data={"shop_id": demo["shop_id"], "facts": facts, "languages": "ru"}, files=files or [])


def test_endpoint_uses_live_model_and_records_cost(client, demo, live_on, monkeypatch):
    client.post("/v1/ai/consent", headers=demo["headers"], json={"granted": True})
    monkeypatch.setattr(draft_ai, "live_draft", lambda facts, photos, transport=None: draft_ai.LiveResult(
        draft=draft_ai.check_draft(_good(), FACTS), tin=1000, tout=300, photos_sent=len(photos)))
    r = _draft(client, demo, files=[("photos", ("a.png", PNG, "image/png"))])
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["generatedBy"] == "ai" and len(body["titles"]) == 3
    assert "Черновик ИИ — проверьте перед публикацией" in body["warnings"][0]
    with DbSession(engine) as db:
        rows = db.scalars(select(AIUsageEvent).where(AIUsageEvent.kind == "draft", AIUsageEvent.shop_id == demo["shop_id"])).all()
        assert rows and rows[-1].cost_micro_usd > 0


def test_endpoint_falls_back_to_template_when_model_fails(client, demo, live_on, monkeypatch):
    client.post("/v1/ai/consent", headers=demo["headers"], json={"granted": True})

    def boom(facts, photos, transport=None):
        raise draft_ai.DraftFallback("ошибка модели 529")

    monkeypatch.setattr(draft_ai, "live_draft", boom)
    r = _draft(client, demo)
    assert r.status_code == 201
    assert r.json()["generatedBy"] == "template"
    assert r.json()["warnings"][0].startswith("Составлено по шаблону: ИИ не смог составить проверяемый черновик")


def test_endpoint_template_when_assistant_is_off(client, demo, live_on, monkeypatch):
    client.post("/v1/ai/consent", headers=demo["headers"], json={"granted": True})
    monkeypatch.setattr(api_module, "is_enabled", lambda db, key: False if key == "ai_assistant" else True)
    r = _draft(client, demo)
    assert r.status_code == 201 and r.json()["generatedBy"] == "template"
    assert "помощник сейчас выключен" in r.json()["warnings"][0]


def test_endpoint_template_when_budget_is_exhausted(client, demo, live_on, monkeypatch):
    client.post("/v1/ai/consent", headers=demo["headers"], json={"granted": True})

    def exhausted(db, now):
        raise ApiError(503, "ai_budget_exhausted", "x")

    monkeypatch.setattr(api_module.ai_service, "require_budget", exhausted)
    r = _draft(client, demo)
    assert r.status_code == 201 and r.json()["generatedBy"] == "template"
    assert "бюджет ИИ на сегодня исчерпан" in r.json()["warnings"][0]


def test_endpoint_rejects_oversize_and_wrong_photos(client, demo, live_on):
    client.post("/v1/ai/consent", headers=demo["headers"], json={"granted": True})
    r = _draft(client, demo, files=[("photos", ("a.gif", b"GIF89a" + b"0" * 20, "image/gif"))])
    assert r.status_code == 422
    big = b"\x89PNG\r\n\x1a\n" + b"0" * (draft_ai.MAX_PHOTO_BYTES + 10)
    r = _draft(client, demo, files=[("photos", ("big.png", big, "image/png"))])
    assert r.status_code == 422 and "5 МБ" in r.json()["error"]["message"]


def test_endpoint_works_without_separate_consent(client, demo, live_on, monkeypatch):
    """К-24: согласие на ИИ входит в галочку условий; отдельного шага нет. Модель не вызываем — шаблон."""
    monkeypatch.setattr(settings, "anthropic_api_key", "")
    r = _draft(client, demo)
    assert r.status_code == 201, r.text
