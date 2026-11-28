"""QA-03, QA-04, QA-05: бюджет ИИ, черновики в квоте, метка «ответ создан ИИ»."""

from datetime import datetime, timezone

from sqlalchemy.orm import Session as DbSession

from app import ai as ai_service
from app.config import settings
from app.db import engine


def _consent(client, demo):
    client.post("/v1/ai/consent", json={"granted": True}, headers=demo["headers"])


def test_reply_drafts_count_toward_the_shared_daily_quota(client, demo, live_reply_ok):
    _consent(client, demo)
    url = f"/v1/ai/reply-drafts?shop_id={demo['shop_id']}"
    kinds = [client.post(url, json={"question": f"Где заказ {i}?", "tone": "polite"},
                         headers=demo["headers"]).json()["generatedBy"] for i in range(31)]
    assert kinds[:30] == ["ai"] * 30
    assert kinds[30] == "template"  # К-35: лимит исчерпан — шаблон с пометкой, а не ошибка


def test_invalid_draft_input_does_not_spend_quota(client, demo):
    _consent(client, demo)
    url = f"/v1/ai/reply-drafts?shop_id={demo['shop_id']}"
    bad = client.post(url, json={"question": "   ", "tone": "polite"}, headers=demo["headers"])
    assert bad.status_code == 422
    with DbSession(engine) as db:
        from app.models import AIUsageEvent
        from sqlalchemy import func, select
        assert db.scalar(select(func.count()).select_from(AIUsageEvent)) == 0


def test_budget_exhaustion_stops_the_assistant(client, demo, monkeypatch):
    # дневной бюджет = месячный / 20; один вызов по 10 $ при месячном 200 $ — дневной 10 $ исчерпан
    monkeypatch.setattr(settings, "ai_budget_monthly_usd", 200.0)
    monkeypatch.setattr(settings, "ai_cost_per_call_micro_usd", 10_000_000)
    _consent(client, demo)
    url = f"/v1/shops/{demo['shop_id']}/ai/ask"
    assert client.post(url, json={"question": "Сколько прибыли?"}, headers=demo["headers"]).status_code == 200
    r = client.post(url, json={"question": "А за неделю?"}, headers=demo["headers"])
    assert r.status_code == 503
    assert r.json()["error"]["code"] == "ai_budget_exhausted"
    assert "Отчёты работают как обычно" in r.json()["error"]["message"]


def test_budget_warns_at_eighty_percent(client, demo, monkeypatch):
    monkeypatch.setattr(settings, "ai_budget_monthly_usd", 100.0)  # дневной 5 $
    monkeypatch.setattr(settings, "ai_cost_per_call_micro_usd", 4_000_000)  # 4 $ = 80% дневного
    _consent(client, demo)
    assert client.post(f"/v1/shops/{demo['shop_id']}/ai/ask", json={"question": "Прибыль?"},
                       headers=demo["headers"]).status_code == 200
    with DbSession(engine) as db:
        state = ai_service.budget_state(db, datetime.now(timezone.utc))
    assert state["level"] == "warn"
    assert state["daySpentUsd"] == 4.0


def test_every_answer_is_labelled_as_generated_by_ai(client, demo, live_reply_ok):
    _consent(client, demo)
    ask = client.post(f"/v1/shops/{demo['shop_id']}/ai/ask", json={"question": "Прибыль за неделю?"},
                      headers=demo["headers"])
    assert ask.status_code == 200
    assert ask.json()["generatedBy"] == "ai"
    reply = client.post(f"/v1/ai/reply-drafts?shop_id={demo['shop_id']}",
                        json={"question": "Где заказ?", "tone": "short"}, headers=demo["headers"])
    assert reply.status_code == 201
    assert reply.json()["generatedBy"] == "ai"
