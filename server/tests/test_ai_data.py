"""Шаг 5 трека 3.8: остатки — «данных нет» (честный ответ); налог — отдельная фикстура, эталонные данные не меняются."""

from datetime import datetime, timezone

from sqlalchemy.orm import Session as DbSession

from app import ai as ai_service
from app.db import engine
from app.models import Shop, TaxRate


def _ask(shop_id, question):
    with DbSession(engine) as db:
        out = ai_service.ask(db, db.get(Shop, shop_id), question, None, None, now=datetime.now(timezone.utc))
        db.commit()
        return out


def test_stock_question_gets_honest_no_data_answer(demo):
    out = _ask(demo["shop_id"], "сколько осталось увлажнителя на складе")
    assert ai_service.NO_STOCK_RU in out["renderedAnswer"]
    assert not any(ch.isdigit() for ch in out["renderedAnswer"])
    assert out["missingData"] == ["Нет данных об остатках"]


def test_stock_question_in_kazakh_is_answered_in_russian(demo):
    """К-13 (22.11): вопрос на казахском понимаем, ответ — всегда по-русски."""
    out = _ask(demo["shop_id"], "Қойманың қалдығы қанша?")
    assert out["lang"] == "ru"
    assert not any(ch in "әғқңөұүһі" for ch in out["renderedAnswer"].lower())


def test_tax_rate_fixture_is_isolated_to_its_shop(demo, client):
    """Фикстура налога: ставка добавляется только в тестовый магазин этого теста; общие демо-данные не меняются."""
    with DbSession(engine) as db:
        db.add(TaxRate(shop_id=demo["shop_id"], rate_bp=400, effective_from=None))
        db.commit()
    out = _ask(demo["shop_id"], "налог за прошлый месяц сколько")
    assert "налог" in out["renderedAnswer"].lower()
    other = client.post("/v1/demo/session", headers={"X-Device-Id": "tax-other-0003"}).json()["shop_id"]
    with DbSession(engine) as db:
        assert db.query(TaxRate).filter(TaxRate.shop_id == other).count() == 0
