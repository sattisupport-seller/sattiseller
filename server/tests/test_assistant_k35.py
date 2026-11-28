"""К-35 п.7: ответ помощника — без «7d» и повтора слов; сравнение 14 к 14; «прибыль не посчитана» вместо «−100 %»."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import Session as DbSession

from app import ai as ai_service
from app.db import engine
from app.models import Order, Shop
from app.reports import base_for


@pytest.mark.parametrize("raw,clean", [
    ("За период «7d» заказов стало 8 заказов, а прибыль снизилась.", "За 7 дней заказов стало 8, а прибыль снизилась."),
    ("Сравнение 14d и prev14d: заказов было 12 заказов.", "Сравнение за 14 дней и за предыдущие 14 дней: заказов было 12."),
    ("В период 7d всё хорошо.", "За 7 дней всё хорошо."),
    ("Товаров стало 3 товара.", "Товаров стало 3."),
    ("Прибыль за 7 дней выросла на 5 000 ₸.", "Прибыль за 7 дней выросла на 5 000 ₸."),
])
def test_answer_text_cleanup(raw, clean):
    assert ai_service.clean_answer_text(raw) == clean


def _tools(demo):
    with DbSession(engine) as db:
        shop = db.get(Shop, demo["shop_id"])
        data, facts = base_for(db, shop)
    return ai_service.Tools(data, facts, datetime.now(timezone.utc))


def test_compare_14_days_with_previous_14(demo):
    tools = _tools(demo)
    pa = ai_service._period_arg(tools, "14d")
    pb = ai_service._period_arg(tools, "prev14d")
    assert (pa.end - pa.start).days == 13 and (pb.end - pb.start).days == 13
    assert pb.end == pa.start - timedelta(days=1)


def test_profit_not_ready_instead_of_minus_100(demo):
    """Заказы последних 7 дней ещё не выданы — прибыль периода не посчитана, процент падения не даём."""
    now = datetime.now(timezone.utc)
    with DbSession(engine) as db:
        cut = now - timedelta(days=8)
        for o in db.query(Order).filter(Order.shop_id == demo["shop_id"]):
            if o.created_at.replace(tzinfo=timezone.utc) >= cut or (
                    o.completed_at and o.completed_at.replace(tzinfo=timezone.utc) >= cut):
                o.status, o.completed_at = "in_progress", None
        db.commit()
    tools = _tools(demo)
    facts: list = []
    out = ai_service.execute_tool("compare_periods", {"period_a": "7d", "period_b": "prev7d"}, tools, facts)
    assert "profit_not_ready" in out and "profit_change_pct" not in out
    note = next(f for f in facts if f.label == "profit_not_ready")
    assert "ещё не посчитана" in str(note.value)
