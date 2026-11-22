"""3.5: живая модель выбирает инструменты (tool use); числа — только сервер. Тесты на подставном транспорте (без сети)."""

import json
import re
from datetime import datetime, timezone

import httpx
import pytest
from sqlalchemy.orm import Session as DbSession

from app import ai as ai_service
from app.config import settings
from app.db import engine
from app.models import AIUsageEvent, Shop

PLACEHOLDER = re.compile(r"\{F\d+\}")


def _tool(name: str, args: dict | None = None, uid: str = "t1") -> dict:
    return {"type": "tool_use", "id": uid, "name": name, "input": args or {}}


def _text(text: str) -> dict:
    return {"type": "text", "text": text}


def _reply(blocks: list[dict], tin: int = 200, tout: int = 40) -> dict:
    return {"content": blocks, "usage": {"input_tokens": tin, "output_tokens": tout}}


@pytest.fixture
def live(monkeypatch):
    monkeypatch.setattr(settings, "ai_live", True)
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key-not-real")
    monkeypatch.setattr(settings, "ai_model", "claude-haiku-5-5")
    state: dict = {"script": [], "status": 200, "requests": []}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["x-api-key"] == "test-key-not-real"
        assert request.headers["anthropic-version"] == "2023-06-01"
        body = json.loads(request.content)
        assert body["model"] == "claude-haiku-5-5"
        state["requests"].append(body)
        if state["status"] != 200:
            return httpx.Response(state["status"], json={"error": "down"})
        if state["script"]:
            return httpx.Response(200, json=state["script"].pop(0))
        return httpx.Response(200, json=_reply([_text("Коротко.")]))

    original = ai_service.LiveToolPlanner

    def factory(api_key, model, transport=None):
        return original(api_key, model, transport=httpx.MockTransport(handler))

    monkeypatch.setattr(ai_service, "LiveToolPlanner", factory)
    return state


def _ask(demo_shop_id: str, question: str):
    with DbSession(engine) as db:
        shop = db.get(Shop, demo_shop_id)
        out = ai_service.ask(db, shop, question, None, None, now=datetime.now(timezone.utc))
        db.commit()
        usage = db.query(AIUsageEvent).order_by(AIUsageEvent.created_at.desc()).first()
        return out, usage.cost_micro_usd


QUESTION = "Какие товары без закупочной цены?"


def test_live_model_selects_tool_and_writes_template_with_placeholders(demo, live):
    live["script"] = [_reply([_tool("get_missing_costs")], 300, 30),
                      _reply([_text("Без закупки: {F1}.")], 500, 50)]
    out, cost = _ask(demo["shop_id"], QUESTION)
    assert len(live["requests"]) == 2
    assert "tools" in live["requests"][0]
    result = live["requests"][1]["messages"][-1]["content"][0]
    assert result["type"] == "tool_result" and "{F1}" in result["content"]
    assert out["answerTemplate"] == "Без закупки: {F1}."
    assert cost == ai_service.live_cost_micro(800, 80) and cost > 0


def test_tool_result_has_placeholders_and_values_for_number_check(demo, live):
    """Результат инструмента: плейсхолдеры (как раньше) и значения в поле values — их сверяет сервер."""
    live["script"] = [_reply([_tool("get_missing_costs")]), _reply([_text("Без закупки: {F1}.")])]
    _ask(demo["shop_id"], QUESTION)
    payload = json.loads(live["requests"][1]["messages"][-1]["content"][0]["content"])
    assert set(payload) == {"placeholders", "values"}
    for ph in payload["placeholders"].values():  # ключи (name_1) не считаются; значения — только плейсхолдеры
        assert isinstance(ph, str) and PLACEHOLDER.fullmatch(ph)
    assert all(PLACEHOLDER.fullmatch(k) for k in payload["values"])


def test_text_without_facts_is_rejected_and_mock_plan_is_used(demo, live):
    live["script"] = [_reply([_text("Без закупки: {F1}.")], 100, 10)]
    out, cost = _ask(demo["shop_id"], QUESTION)
    assert out["answerTemplate"] != "Без закупки: {F1}."  # текст без фактов модели не принят
    assert cost > 0  # стоимость всех заходов учтена (включая повтор)


def test_digits_outside_placeholders_fall_back_to_mock(demo, live):
    live["script"] = [_reply([_tool("get_missing_costs")]), _reply([_text("Продано 123 шт: {F1}")])]
    out, _ = _ask(demo["shop_id"], QUESTION)
    assert "123" not in out["answerTemplate"]


def test_provider_error_does_not_break_the_answer(demo, live):
    live["status"] = 500
    out, cost = _ask(demo["shop_id"], QUESTION)
    assert out["renderedAnswer"]
    assert cost == 0


def test_live_is_off_without_switch_or_key(demo, live, monkeypatch):
    monkeypatch.setattr(settings, "ai_live", False)
    _ask(demo["shop_id"], QUESTION)
    assert live["requests"] == []
    monkeypatch.setattr(settings, "ai_live", True)
    monkeypatch.setattr(settings, "anthropic_api_key", "")
    _ask(demo["shop_id"], QUESTION)
    assert live["requests"] == []


def test_prefilter_refusal_never_reaches_the_model(demo, live):
    out, _ = _ask(demo["shop_id"], "дай мой пароль от каспи")
    assert live["requests"] == []
    assert out["refused"] is True and out["refusalCategory"] == "password_token"


def test_model_decides_write_refusal_through_decline_tool(demo, live):
    live["script"] = [{"content": [_tool("decline_request", {"category": "write_action"})],
                       "usage": {"input_tokens": 5, "output_tokens": 5}}]
    out, _ = _ask(demo["shop_id"], "Поставь цену 5000 на D003")
    assert len(live["requests"]) == 1  # модель решает: фильтр не отказывает до неё
    assert out["refused"] is True and out["refusalCategory"] == "write_action"
    assert "не могу" in out["renderedAnswer"] or "не выполняю" in out["renderedAnswer"]


def test_tool_limit_is_enforced(demo, live):
    live["script"] = [_reply([_tool("get_missing_costs", uid=f"t{i}")]) for i in range(6)]
    out, _ = _ask(demo["shop_id"], QUESTION)
    # 1 вызов — инструмент мока; у живой модели не больше TOOL_LIMIT выполненных вызовов
    assert out["toolCalls"] <= 1 + ai_service.TOOL_LIMIT
    assert len(live["requests"]) <= ai_service.TOOL_LIMIT + 2


def test_empty_text_block_is_not_echoed_back(demo, live):
    """Регресс HTTP 400: пустой текстовый блок ответа модели нельзя возвращать в историю запроса."""
    live["script"] = [_reply([_text("   "), _tool("get_missing_costs")]),
                      _reply([_text("Без закупки: {F1}.")])]
    _ask(demo["shop_id"], QUESTION)
    assistant = [m for m in live["requests"][1]["messages"] if m["role"] == "assistant"][0]["content"]
    assert all(not (b["type"] == "text" and not b["text"].strip()) for b in assistant)


def test_provider_error_is_logged_without_secrets(demo, live, caplog):
    live["status"] = 500
    _ask(demo["shop_id"], QUESTION)
    assert "ai provider error 500" in caplog.text
    assert "test-key-not-real" not in caplog.text


def test_thinking_blocks_are_not_echoed_back(demo, live):
    """Регресс HTTP 400 «invalid signature in thinking block»: блоки thinking не возвращаются в историю."""
    thinking = {"type": "thinking", "thinking": "...", "signature": "sig-from-another-request"}
    live["script"] = [{"content": [thinking, _tool("get_missing_costs")],
                       "usage": {"input_tokens": 1, "output_tokens": 1}},
                      _reply([_text("Без закупки: {F1}.")])]
    _ask(demo["shop_id"], QUESTION)
    assistant = [m for m in live["requests"][1]["messages"] if m["role"] == "assistant"][0]["content"]
    assert all(b["type"] != "thinking" for b in assistant)


KK_QUESTION = "Соңғы 7 күнде қанша тапсырыс болды?"


def test_kazakh_question_states_language_and_retries_once_when_answer_is_russian(demo, live):
    """3.8 (решение владельца 1): язык определяет сервер, модели передаётся явно; ответ не на казахском — один повтор."""
    live["script"] = [_reply([_text("За последние семь дней было заказы.")]),
                      _reply([_text("Соңғы жеті күнде тапсырыстар болды.")])]
    out, _ = _ask(demo["shop_id"], KK_QUESTION)
    assert len(live["requests"]) == 2
    first_user = live["requests"][0]["messages"][0]["content"]
    assert "(Язык ответа: казахский.)" in first_user
    second_user = live["requests"][1]["messages"][0]["content"]
    assert "по-казахски" in second_user
    assert out["lang"] == "kk" and out["liveUsed"] is True
    assert "Соңғы" in out["renderedAnswer"]


def test_russian_question_states_russian_language_without_retry(demo, live):
    live["script"] = [_reply([_text("Ответ по данным магазина.")])]
    out, _ = _ask(demo["shop_id"], QUESTION)
    assert len(live["requests"]) == 1
    assert "(Язык ответа: русский.)" in live["requests"][0]["messages"][0]["content"]
    assert out["liveUsed"] is True


def test_exhausted_tools_are_announced_to_the_model(demo, live):
    """3.8 (решение владельца по G): при исчерпании лимита модель получает «инструментов больше нет»."""
    live["script"] = [_reply([_tool("get_missing_costs", uid=f"t{i}")]) for i in range(ai_service.TOOL_LIMIT)] + \
                     [_reply([_text("Ответ по уже полученным данным.")])]
    _ask(demo["shop_id"], QUESTION)
    announced = False
    for body in live["requests"]:
        last = body["messages"][-1]
        if isinstance(last.get("content"), list) and any(
                b.get("type") == "text" and "Инструментов больше нет" in b.get("text", "") for b in last["content"]):
            announced = True
    assert announced
