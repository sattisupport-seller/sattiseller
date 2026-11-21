"""1.4: письмо владельцу при 80% и 100% месячного бюджета ИИ — проверка на реальных записях расходов.

Дневной лимит (1/20 месячного) в этом тесте поднят явно, чтобы не сработать раньше месячного порога.
"""

from datetime import datetime, timezone

import pytest
from sqlalchemy.orm import Session as DbSession

from app import ai as ai_service
from app.config import settings
from app.db import engine
from app.models import AIBudgetAlert


@pytest.fixture
def budget(monkeypatch):
    monkeypatch.setattr(settings, "ai_budget_monthly_usd", 10.0)
    monkeypatch.setattr(settings, "ai_budget_daily_usd", 1000.0)  # дневной лимит не мешает месячному
    monkeypatch.setattr(settings, "ai_cost_per_call_micro_usd", 1_000_000)  # 1 USD за вызов
    monkeypatch.setattr(settings, "owner_alert_email", "owner@example.invalid")
    sent: list[str] = []
    monkeypatch.setattr(ai_service, "send_owner_alert", lambda subject, text: sent.append(subject) or True)
    return sent


def test_alerts_at_80_and_100_percent_only_once_each(budget):
    now = datetime.now(timezone.utc)
    shop = "shop-budget-test"
    with DbSession(engine) as db:
        for call in range(1, 12):
            ai_service.record_usage(db, None, shop, now, "question")
            db.commit()
            state = ai_service.budget_state(db, now)
            if call == 7:
                assert state["level"] == "ok"  # 70%: письма нет
                assert budget == []
            if call == 8:
                assert state["level"] == "warn"  # 80%
                assert len(budget) == 1 and "80%" in budget[0]
            if call == 9:
                assert len(budget) == 1  # повтор на том же уровне не отправляется
            if call == 10:
                assert state["level"] == "exhausted"  # 100%
                assert len(budget) == 2 and "исчерпан" in budget[1]
        assert len(budget) == 2  # после 100% письма больше нет
        levels = sorted(r.level for r in db.query(AIBudgetAlert).all())
    assert levels == ["exhausted", "warn"]
