"""К-35 п.2: ответ покупателю — живой ИИ по сути вопроса; проверка ответа кодом; шаблон по теме, когда ИИ недоступен."""

import json

import httpx
import pytest

from app import ai as ai_service
from app import draft_ai
from app.config import settings

QUESTIONS = [
    ("доставка ехал очень долго", "доставк"),
    ("Курьер так и не привёз заказ, где он?", "доставк"),
    ("Стакан пришёл разбитый, трещина по краю", "фото"),
    ("Товар не работает с первого дня", "фото"),
    ("Хочу вернуть, не подошёл размер", "возврат"),
    ("Можно поменять на другой цвет?", "Kaspi"),
    ("Есть ли в наличии чёрный цвет?", "наличие"),
    ("Когда отправите заказ?", "срок"),
    ("Сколько дней идёт доставка в Караганду?", "достав"),
    ("Спасибо, всё понравилось!", "Спасибо"),
]


@pytest.mark.parametrize("question,expect", QUESTIONS)
def test_template_answers_by_topic_not_with_one_phrase(question, expect):
    reply = ai_service.reply_template(question, "polite")
    assert reply.startswith("Здравствуйте!")
    assert "Уточните, пожалуйста, что именно вас интересует" not in reply
    assert expect.lower() in reply.lower(), (question, reply)
    assert not draft_ai.MONEY_PROMISE.search(reply) and not any(ch.isdigit() for ch in reply)


def test_templates_differ_across_topics():
    replies = {ai_service.reply_template(q, "short") for q, _ in QUESTIONS}
    assert len(replies) >= 5


# --- проверка ответа модели ---------------------------------------------------------------------------------------

GOOD = "Здравствуйте! Нам жаль, что доставка заняла столько времени. Мы проверим, что случилось, и напишем вам."


@pytest.mark.parametrize("bad,why", [
    ("Здравствуйте! Мы вернём деньги за доставку и дадим скидку.", "деньги"),
    ("Здравствуйте! Предлагаем компенсацию за ожидание.", "компенсация"),
    ("Здравствуйте! Напишите нам: shop@example.com", "контакт"),
    ("Здравствуйте! Заказ придёт через 2 дня.", "выдуманный срок"),
    ("Сәлеметсіз бе! Тапсырыс жақында келеді.", "не русский"),
    ("", "пусто"),
])
def test_bad_model_replies_are_rejected(bad, why):
    with pytest.raises(draft_ai.DraftFallback):
        draft_ai.check_reply(bad, "доставка ехал очень долго")


def test_numbers_from_question_are_allowed():
    assert draft_ai.check_reply("Здравствуйте! Заказ на 400 мл проверим и ответим.", "стакан 400 мл не пришёл")


# --- эндпоинт -----------------------------------------------------------------------------------------------------

def _model(text: str):
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert "компенсац" in body["system"]  # правила — в системном тексте
        assert "+7" not in body["messages"][0]["content"]  # телефон замаскирован до отправки
        return httpx.Response(200, json={"content": [{"type": "text", "text": text}],
                                         "usage": {"input_tokens": 300, "output_tokens": 60}})
    return httpx.MockTransport(handler)


@pytest.fixture
def live(monkeypatch):
    monkeypatch.setattr(settings, "ai_live", True)
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    state = {"text": GOOD}
    real = draft_ai.live_reply
    monkeypatch.setattr(draft_ai, "live_reply", lambda q, tone: real(q, tone, transport=_model(state["text"])))
    return state


def _ask(client, demo, question, tone="polite"):
    client.post("/v1/ai/consent", json={"granted": True}, headers=demo["headers"])
    return client.post(f"/v1/ai/reply-drafts?shop_id={demo['shop_id']}", headers=demo["headers"],
                       json={"question": question, "tone": tone})


def test_live_reply_answers_the_question(client, demo, live):
    r = _ask(client, demo, "доставка ехал очень долго, звоните +7 701 000 00 00")
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["generatedBy"] == "ai" and body["reply"] == GOOD
    assert any("личные данные" in w for w in body["warnings"])


def test_unsafe_model_reply_falls_back_to_topic_template(client, demo, live):
    live["text"] = "Здравствуйте! Вернём деньги и дадим промокод на 500 тенге."
    body = _ask(client, demo, "доставка ехал очень долго").json()
    assert body["generatedBy"] == "template"
    assert "задержк" in body["reply"] and "не прошёл проверку" in body["warnings"][0]


def test_daily_limit_gives_template_with_note(client, demo, live, monkeypatch):
    monkeypatch.setattr(settings, "ai_daily_limit", 2)
    assert [_ask(client, demo, f"Где заказ {i}?").json()["generatedBy"] for i in range(2)] == ["ai", "ai"]
    third = _ask(client, demo, "Где заказ?")
    assert third.status_code == 201
    assert third.json()["generatedBy"] == "template" and "лимит" in third.json()["warnings"][0]


def test_without_live_ai_template_and_no_quota_spent(client, demo, monkeypatch):
    monkeypatch.setattr(settings, "ai_live", False)
    body = _ask(client, demo, "Есть ли в наличии?").json()
    assert body["generatedBy"] == "template" and "наличие" in body["reply"]
    from sqlalchemy import func, select
    from sqlalchemy.orm import Session as DbSession

    from app.db import engine
    from app.models import AIUsageEvent
    with DbSession(engine) as db:
        assert db.scalar(select(func.count()).select_from(AIUsageEvent)) == 0
