"""3.8 (бета): оценка ответа сохраняет вопрос с маскировкой, признак отказа и категорию."""

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.db import engine
from app.models import AIFeedback


def _last_feedback() -> AIFeedback:
    with DbSession(engine) as db:
        return db.scalars(select(AIFeedback).order_by(AIFeedback.created_at.desc())).first()


def test_feedback_keeps_masked_question_and_refusal_flag(client, demo):
    shop = demo["shop_id"]
    client.post("/v1/ai/consent", headers=demo["headers"], json={"granted": True})
    q = "Поставь цену D001 100 тенге, мой номер +7 701 123 45 67"
    ask = client.post(f"/v1/shops/{shop}/ai/ask", headers=demo["headers"], json={"question": q})
    assert ask.status_code == 200
    turn = ask.json()["turnId"]
    fb = client.post("/v1/ai/feedback", headers=demo["headers"],
                     json={"shop_id": shop, "turn_id": turn, "kind": "down", "reason": "wrong_numbers"})
    assert fb.status_code == 201
    row = _last_feedback()
    assert row.kind == "down"
    assert row.refused is True and row.refusal_category == "write_action"
    assert row.question_masked is not None
    assert "123 45 67" not in row.question_masked and "+7" not in row.question_masked  # телефон замаскирован
    assert "Поставь цену" in row.question_masked  # текст вопроса сохранён


def test_feedback_for_answer_keeps_refused_false(client, demo):
    shop = demo["shop_id"]
    client.post("/v1/ai/consent", headers=demo["headers"], json={"granted": True})
    ask = client.post(f"/v1/shops/{shop}/ai/ask", headers=demo["headers"], json={"question": "Какие товары в минус?"})
    turn = ask.json()["turnId"]
    client.post("/v1/ai/feedback", headers=demo["headers"],
                json={"shop_id": shop, "turn_id": turn, "kind": "up"})
    row = _last_feedback()
    assert row.kind == "up" and row.refused is False and row.refusal_category is None
