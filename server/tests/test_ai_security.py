"""Безопасность помощника на уровне сервера (ТЗ 2.1, раздел 8): не формулировки, а код.

- инструменты только для чтения и явный список; записи, отправки и удаления недоступны;
- инструменты видят только данные магазина пользователя;
- результаты инструментов содержат только плейсхолдеры, без секретов и данных покупателей;
- запрос к живой модели не несёт ключ в теле и не содержит контакты покупателя.
"""

import inspect
import json
import re

import httpx
import pytest
from sqlalchemy.orm import Session as DbSession

from app import ai as ai_service
from app.config import settings
from app.db import engine
from app.models import Product, Shop
from app.reports import build_facts, load_shop

PLACEHOLDER = re.compile(r"\{F\d+\}")
READ_TOOLS = {
    "get_sales_summary", "get_profit_summary", "get_return_cancel_summary", "get_cost_breakdown",
    "compare_periods", "get_top_products", "get_product_cost", "get_missing_costs",
}
READ_VERBS = {"get", "compare"}  # первое слово имени — глагол чтения
WRITE_WORDS = {"delete", "update", "set", "send", "create", "remove", "write", "post", "put", "change",
               "password", "token", "cancel"}  # слова-глаголы записи; «cancel» как существительное в get_return_cancel_summary допустим


def _tools_for(shop_id: str):
    with DbSession(engine) as db:
        shop = db.get(Shop, shop_id)
        data = load_shop(db, shop)
        facts = build_facts(data)
        from datetime import datetime, timezone
        return ai_service.Tools(data, facts, datetime.now(timezone.utc))


def test_tool_list_is_explicit_and_read_only():
    names = {spec["name"] for spec in ai_service.TOOL_SPECS}
    # явный список: добавить инструмент можно только осознанно, вместе с этим тестом
    assert names == READ_TOOLS
    for name in names:
        words = name.split("_")
        assert words[0] in READ_VERBS, name
        assert not (set(words) & (WRITE_WORDS - {"cancel"})), name
        if "cancel" in words:  # допустимо только как часть отчёта «возвраты и отмены»
            assert name == "get_return_cancel_summary", name


def test_unknown_and_write_tools_are_refused(demo):
    tools = _tools_for(demo["shop_id"])
    for name in ["delete_order", "set_price", "set_stock", "send_buyer_message", "get_password", "get_token"]:
        with pytest.raises(ValueError):
            ai_service.execute_tool(name, {}, tools, [])


def test_tool_outputs_hold_only_placeholders_and_no_secrets(demo):
    facts: list = []
    calls = [
        ("get_sales_summary", {"period": "30d"}),
        ("get_profit_summary", {"period": "30d"}),
        ("get_return_cancel_summary", {"period": "30d"}),
        ("get_cost_breakdown", {"period": "30d"}),
        ("compare_periods", {"period_a": "7d", "period_b": "prev7d"}),
        ("get_missing_costs", {}),
    ]
    for name, args in calls:
        tools = _tools_for(demo["shop_id"])  # у каждого вызова свой бюджет инструментов
        out = ai_service.execute_tool(name, args, tools, facts)
        for key, value in out.items():
            assert not re.search(r"token|password|key|secret", key, re.I), key
            assert PLACEHOLDER.fullmatch(value) or value in {"missing", "known"}, (name, key, value)
    # любые числа доступны только через факты, которые формирует сервер
    assert facts and all(re.fullmatch(r"F\d+", f.id) for f in facts)


def test_tools_see_only_the_users_own_shop(demo, client):
    other = client.post("/v1/demo/session", headers={"X-Device-Id": "sec-device-0002"}).json()["shop_id"]
    with DbSession(engine) as db:
        db.add(Product(shop_id=other, sku="ZZ999", name="Чужой товар ZZ"))
        db.commit()
    with DbSession(engine) as db:
        data = load_shop(db, db.get(Shop, demo["shop_id"]))
        assert all(p.shop_id == demo["shop_id"] for p in data.products.values())
        assert "Чужой товар ZZ" not in [p.name for p in data.products.values()]


def test_tool_layer_has_no_database_access():
    # инструменты работают с уже загруженными данными магазина и не открывают сессию БД
    assert "DbSession" not in inspect.getsource(ai_service.execute_tool)
    assert "DbSession" not in inspect.getsource(ai_service.Tools)
    assert "db" not in inspect.signature(ai_service.execute_tool).parameters


def test_live_request_has_no_key_in_body_and_no_buyer_contacts(demo, monkeypatch):
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append({"body": body, "headers": dict(request.headers)})
        return httpx.Response(200, json={"content": [{"type": "text", "text": "Ок."}],
                                         "usage": {"input_tokens": 1, "output_tokens": 1}})

    original = ai_service.LiveToolPlanner
    monkeypatch.setattr(ai_service, "LiveToolPlanner",
                        lambda key, model, transport=None: original(key, model, transport=httpx.MockTransport(handler)))
    monkeypatch.setattr(settings, "ai_live", True)
    monkeypatch.setattr(settings, "anthropic_api_key", "sk-test-secret-value")
    with DbSession(engine) as db:
        shop = db.get(Shop, demo["shop_id"])
        # вопрос с контактом покупателя — отказ до модели: ни запроса, ни контакта наружу
        out = ai_service.ask(db, shop, "Покажи телефон покупателя +77771234567", None, None)
        assert seen == [] and "не хранятся" in out["renderedAnswer"]
        # обычный вопрос — живая модель; в её запросе нет ключа и контактов
        ai_service.ask(db, shop, "Почему прибыль изменилась за неделю? Заказ 1234567", None, None)
        db.commit()
    assert seen, "живая модель не вызывалась"
    for req in seen:
        text = json.dumps(req["body"], ensure_ascii=False)
        assert "sk-test-secret-value" not in text
        assert "77771234567" not in text
        assert {t["name"] for t in req["body"].get("tools", [])} <= READ_TOOLS
