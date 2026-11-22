"""Числа в ответе живой модели: каждое число проверяется по данным инструментов; один повтор; затем честное сообщение."""

import json
from datetime import datetime, timezone

import httpx
import pytest
from sqlalchemy.orm import Session as DbSession

from app import ai as ai_service
from app.config import settings
from app.db import engine
from app.models import Shop


def _fact(fid: str, kind: str, value) -> ai_service.Fact:
    return ai_service.Fact(fid, "test", kind, value)


@pytest.mark.parametrize("text, value", [
    ("12 500 ₸", 12500.0),
    ("12,5 тыс.", 12500.0),
    ("1 250 000 тг", 1250000.0),
    ("3 млн", 3000000.0),
])
def test_numbers_are_read_with_formats(text, value):
    assert ai_service._numbers_in(text)[0][0] == pytest.approx(value)


def test_number_from_data_is_allowed_in_any_format():
    facts = [_fact("F1", "money", 1250000)]  # 12 500 ₸ (деньги хранятся в тиынах)
    assert ai_service.number_violations("Выручка {F1}, это 12 500 ₸ и 12,5 тыс.", facts, "ru") == []


def test_invented_number_is_reported():
    facts = [_fact("F1", "money", 1250000)]
    assert ai_service.number_violations("Прибыль 99 999 ₸", facts, "ru") == ["99 999"]


def test_placeholders_do_not_count_as_numbers():
    facts = [_fact("F1", "money", 1250000)]
    assert ai_service.number_violations("Выручка {F1}", facts, "ru") == []


def test_small_numbers_need_exact_data():
    facts = [_fact("F1", "orders", 7)]
    assert ai_service.number_violations("Заказов {F1}, это 14 дней", facts, "ru") == ["14"]


@pytest.fixture
def live(monkeypatch):
    monkeypatch.setattr(settings, "ai_live", True)
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key-not-real")
    monkeypatch.setattr(settings, "ai_model", "claude-haiku-5-5")
    state: dict = {"script": [], "requests": []}

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        state["requests"].append(body)
        if state["script"]:
            return httpx.Response(200, json=state["script"].pop(0))
        return httpx.Response(200, json={"content": [{"type": "text", "text": "Коротко."}],
                                         "usage": {"input_tokens": 1, "output_tokens": 1}})

    original = ai_service.LiveToolPlanner

    def factory(api_key, model, transport=None):
        return original(api_key, model, transport=httpx.MockTransport(handler))

    monkeypatch.setattr(ai_service, "LiveToolPlanner", factory)
    return state


def _reply(text: str) -> dict:
    return {"content": [{"type": "text", "text": text}], "usage": {"input_tokens": 10, "output_tokens": 5}}


def _ask(shop_id: str, question: str):
    with DbSession(engine) as db:
        shop = db.get(Shop, shop_id)
        out = ai_service.ask(db, shop, question, None, None, now=datetime.now(timezone.utc))
        db.commit()
        return out


def test_invented_number_gets_one_retry_with_hint(demo, live):
    live["script"] = [_reply("Прибыль 99 999 ₸."), _reply("Прибыль уточню по данным.")]
    out = _ask(demo["shop_id"], "Какая прибыль за неделю?")
    assert out["answerTemplate"] == "Прибыль уточню по данным."
    assert len(live["requests"]) == 2
    assert "Служебная подсказка проверки" in json.dumps(live["requests"][1], ensure_ascii=False)
    assert out["liveUsed"] is True


def test_two_invented_answers_are_rebuilt_from_tools_not_mock_or_failure(demo, live):
    live["script"] = [_reply("Прибыль 99 999 ₸."), _reply("Прибыль 88 888 ₸.")]
    out = _ask(demo["shop_id"], "Какая прибыль за неделю?")
    # Решение владельца 22.11: неверный живой ответ пересобирается из данных инструментов, а не уходит текстом сбоя
    assert out["answerTemplate"] != ai_service.LIVE_FAILED_TEXT["ru"]
    assert out["liveUsed"] is False
    assert "99 999" not in out["renderedAnswer"] and "88 888" not in out["renderedAnswer"]


def test_tool_payload_carries_values_for_the_model(demo, live):
    live["script"] = [
        {"content": [{"type": "tool_use", "id": "t1", "name": "get_missing_costs", "input": {}}],
         "usage": {"input_tokens": 1, "output_tokens": 1}},
        _reply("Без закупки: {F1}."),
    ]
    _ask(demo["shop_id"], "Какие товары без закупочной цены?")
    result = live["requests"][1]["messages"][-1]["content"][0]["content"]
    payload = json.loads(result)
    assert set(payload) == {"placeholders", "values"}
    assert all(str(v).startswith("{F") for v in payload["placeholders"].values() if isinstance(v, str)
               and v.startswith("{F"))


def test_number_the_seller_typed_is_allowed():
    """«За 14 дней» из вопроса продавца — не выдумка модели, а его собственное число."""
    facts = [_fact("F1", "money", 1250000)]
    assert ai_service.number_violations("Прибыль за 14 дней: {F1}", facts, "ru", "какая прибыль за 14 дней") == []
    assert ai_service.number_violations("Прибыль за 21 день: {F1}", facts, "ru", "какая прибыль за 14 дней") == ["21"]
