"""3.5: живая модель переписывает формулировку; числа — только сервер. Тесты на подставном транспорте (без сети)."""

import json
from datetime import datetime, timezone

import httpx
import pytest
from sqlalchemy.orm import Session as DbSession

from app import ai as ai_service
from app.config import settings
from app.db import engine
from app.models import AIUsageEvent, Shop


@pytest.fixture
def live(monkeypatch):
    monkeypatch.setattr(settings, "ai_live", True)
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key-not-real")
    monkeypatch.setattr(settings, "ai_model", "claude-haiku-5-5")
    state = {"response": None, "status": 200, "calls": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        state["calls"] += 1
        assert request.headers["x-api-key"] == "test-key-not-real"
        assert request.headers["anthropic-version"] == "2023-06-01"
        body = json.loads(request.content)
        assert body["model"] == "claude-haiku-5-5"
        if state["response"] is None:  # эхо: та же формулировка с плейсхолдерами из запроса
            payload = json.loads(body["messages"][0]["content"])
            text = "Коротко. " + payload["template"]
            state["response"] = {"content": [{"type": "text", "text": text}],
                                 "usage": {"input_tokens": 200, "output_tokens": 40}}
        return httpx.Response(state["status"], json=state["response"])

    original = ai_service.LiveRewriter

    def factory(api_key, model, transport=None):
        return original(api_key, model, transport=httpx.MockTransport(handler))

    monkeypatch.setattr(ai_service, "LiveRewriter", factory)
    return state


def _ask(demo_shop_id: str, question: str):
    with DbSession(engine) as db:
        shop = db.get(Shop, demo_shop_id)
        out = ai_service.ask(db, shop, question, None, None, now=datetime.now(timezone.utc))
        db.commit()
        usage = db.query(AIUsageEvent).order_by(AIUsageEvent.created_at.desc()).first()
        return out, usage.cost_micro_usd


def test_live_rewrite_keeps_placeholders_and_records_real_cost(demo, live):
    out, cost = _ask(demo["shop_id"], "Какие товары в минус?")
    assert live["calls"] == 1
    assert out["answerTemplate"].startswith("Коротко. ")
    assert cost == ai_service.live_cost_micro(200, 40) and cost > 0


def test_empty_or_placeholder_losing_rewrite_is_rejected(demo, live):
    live["response"] = {"content": [{"type": "text", "text": "   "}], "usage": {"input_tokens": 1, "output_tokens": 1}}
    out, cost = _ask(demo["shop_id"], "Какие товары в минус?")
    assert out["renderedAnswer"].strip() and cost == 0


def test_digits_outside_placeholders_fall_back_to_mock_template(demo, live):
    live["response"] = {"content": [{"type": "text", "text": "Продано 123 шт: {F1}"}],
                        "usage": {"input_tokens": 10, "output_tokens": 10}}
    out, cost = _ask(demo["shop_id"], "Какие товары в минус?")
    assert "123" not in out["answerTemplate"]
    assert cost == 0


def test_provider_error_does_not_break_the_answer(demo, live):
    live["status"] = 500
    live["response"] = {"error": "down"}
    out, _ = _ask(demo["shop_id"], "Какие товары в минус?")
    assert out["renderedAnswer"]


def test_live_is_off_without_switch_or_key(demo, live, monkeypatch):
    monkeypatch.setattr(settings, "ai_live", False)
    _ask(demo["shop_id"], "Какие товары в минус?")
    assert live["calls"] == 0
    monkeypatch.setattr(settings, "ai_live", True)
    monkeypatch.setattr(settings, "anthropic_api_key", "")
    _ask(demo["shop_id"], "Какие товары в минус?")
    assert live["calls"] == 0

