"""Инструменты помощника: периоды (ru/kk, 14 дней), допустимые значения, товар по артикулу (регресс)."""

from datetime import datetime, timezone

import pytest
from sqlalchemy.orm import Session as DbSession

from app import ai as ai_service
from app.db import engine
from app.models import Product, Shop
from app.reports import build_facts, load_shop


def _tools(shop_id: str):
    with DbSession(engine) as db:
        data = load_shop(db, db.get(Shop, shop_id))
        return ai_service.Tools(data, build_facts(data), datetime.now(timezone.utc))


@pytest.mark.parametrize("question, period", [
    ("а прибыль за 14 дней какая", "14d"),
    ("за две недели выручка", "14d"),
    ("Соңғы 14 күнде түсім қанша болды?", "14d"),
    ("Осы аптада қанша пайда таптым?", "7d"),
    ("скок я заработал за эту неделю", "7d"),
    ("сколько было возвратов в прошлом месяце", "previous_month"),
    ("сегодня сколько заказов", "today"),
    ("skolko pribyl za 90 dnei", "90d"),
    ("кеше канша прибыль болды", "yesterday"),
])
def test_period_is_normalized_from_question(question, period):
    assert ai_service._period_key(question.lower()) == period


def test_fourteen_day_period_runs_and_is_in_the_enum(demo):
    assert "14d" in ai_service.PRESET_NAMES
    tools = _tools(demo["shop_id"])
    out = ai_service.execute_tool("get_profit_summary", {"period": "14d"}, tools, [])
    assert set(out) == {"period", "profit", "net_sales"}


def test_unknown_period_is_refused(demo):
    tools = _tools(demo["shop_id"])
    with pytest.raises(ValueError):
        ai_service.execute_tool("get_profit_summary", {"period": "2 weeks"}, tools, [])


def test_product_cost_by_sku_returns_known_or_missing(demo):
    """Регресс: products — словарь; поиск по артикулу раньше падал с AttributeError."""
    tools = _tools(demo["shop_id"])
    facts: list = []
    out = ai_service.execute_tool("get_product_cost", {"sku": "D007"}, tools, facts)
    assert out["status"] in {"known", "missing"}
    if out["status"] == "known":
        assert "unit_cost" in out


def test_product_cost_unknown_sku_is_a_value_error(demo):
    tools = _tools(demo["shop_id"])
    with pytest.raises(ValueError):
        ai_service.execute_tool("get_product_cost", {"sku": "NOPE999"}, tools, [])


def test_purchase_question_with_sku_does_not_crash(demo, client):
    """Регресс: путь «закупочная цена + артикул» в мок-плане не должен падать."""
    with DbSession(engine) as db:
        shop = db.get(Shop, demo["shop_id"])
        product = db.query(Product).filter(Product.shop_id == shop.id).first()
        out = ai_service.ask(db, shop, f"какая закупочная цена у {product.sku}", None, None)
        assert out["renderedAnswer"]
