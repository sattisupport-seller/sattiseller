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
    assert {"period", "profit", "net_sales"} <= set(out) <= {"period", "profit", "net_sales", "margin"}


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


def test_compare_periods_uses_one_tool_call(demo):
    """Регресс: сравнение двух периодов раньше расходовало два вызова и срывало лимит (tool limit exceeded)."""
    tools = _tools(demo["shop_id"])
    ai_service.execute_tool("compare_periods", {"period_a": "7d", "period_b": "prev7d"}, tools, [])
    assert tools.calls == 1


def _f(fid, kind, value):
    return ai_service.Fact(fid, "t", kind, value)


def test_calculate_sum_diff_average_and_share():
    facts = [_f("F1", "money", 100000), _f("F2", "money", 150000)]
    assert ai_service.execute_tool("calculate", {"op": "diff", "ids": ["F1", "F2"]}, None, facts)["result"] == "{F3}"
    assert facts[-1].value == 50000 and facts[-1].kind == "money"  # второй минус первый
    ai_service.execute_tool("calculate", {"op": "average", "ids": ["F1", "F2"]}, None, facts)
    assert facts[-1].value == 125000
    ai_service.execute_tool("calculate", {"op": "share", "ids": ["F1", "F2"]}, None, facts)
    assert facts[-1].kind == "percent" and facts[-1].value == 6667  # 66,67% в базисных пунктах


def test_calculate_percent_change_in_basis_points():
    facts = [_f("F1", "money", 100000), _f("F2", "money", 150000)]
    ai_service.execute_tool("calculate", {"op": "pct_change", "ids": ["F1", "F2"]}, None, facts)
    assert facts[-1].kind == "percent" and facts[-1].value == 5000  # +50,00%


@pytest.mark.parametrize("args, facts", [
    ({"op": "power", "ids": ["F1"]}, [_f("F1", "money", 1)]),
    ({"op": "pct_change", "ids": ["F1", "F2"]}, [_f("F1", "money", 0), _f("F2", "money", 5)]),
    ({"op": "share", "ids": ["F1", "F2"]}, [_f("F1", "money", 5), _f("F2", "money", 0)]),
    ({"op": "diff", "ids": ["F9", "F2"]}, [_f("F2", "money", 5)]),
    ({"op": "sum", "ids": ["F1"]}, [_f("F1", "text", "abc")]),
])
def test_calculate_refuses_bad_input(args, facts):
    with pytest.raises(ValueError):
        ai_service.execute_tool("calculate", args, None, facts)


def test_compare_periods_has_difference_and_percent(demo):
    tools = _tools(demo["shop_id"])
    facts: list = []
    out = ai_service.execute_tool("compare_periods", {"period_a": "7d", "period_b": "prev7d"}, tools, facts)
    assert "profit_change" in out
    if "profit_change_pct" in out:
        assert facts[-1].kind in {"money", "percent"}


def test_product_found_by_word_stem(demo):
    """«Термокружки» (родительный падеж) находит «Термокружка 450 мл, нержавейка» по основе слова."""
    tools = _tools(demo["shop_id"])
    facts: list = []
    out = ai_service.execute_tool("get_product_cost", {"name": "Термокружки нержавейка"}, tools, facts)
    assert out["status"] in {"known", "missing"}
    assert facts and "Термокружк" in facts[0].value


def test_top_products_by_quantity_uses_units(demo):
    tools = _tools(demo["shop_id"])
    facts: list = []
    out = ai_service.execute_tool("get_top_products", {"period": "30d", "metric": "qty", "limit": 2}, tools, facts)
    assert set(out) >= {"period", "count"}
    assert all(f.kind in {"units", "external", "text"} for f in facts)


def test_product_margin_and_profit_for_period(demo):
    tools = _tools(demo["shop_id"])
    facts: list = []
    out = ai_service.execute_tool("get_product_cost", {"sku": "D007", "period": "30d"}, tools, facts)
    assert out["status"] in {"known", "missing"}
