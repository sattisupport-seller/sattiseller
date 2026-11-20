"""Маскировка точных значений покупателей из заказов (ADR-0004, задача 3). Kaspi не подключён — заказы фейковые."""

from types import SimpleNamespace

import pytest

from app import ai
from app.privacy import MASK_BUYER, buyer_values, mask_known, mask_text
from tests.conftest import login

FAKE_ORDERS = [
    SimpleNamespace(buyer_name="Айжан Нурланова", buyer_phone="+7 700 111 22 33", buyer_address="Астана, Мангилик Ел 10"),
    SimpleNamespace(buyer_name="Данияр Сейтказы", buyer_phone="87012223344", buyer_address=None),
    SimpleNamespace(buyer_name=None, buyer_phone=None, buyer_address=None),  # пустой заказ — не ломает
]


def test_buyer_values_collects_names_phones_and_address():
    values = buyer_values(FAKE_ORDERS)
    assert "Айжан Нурланова" in values
    assert "Данияр Сейтказы" in values
    assert "Астана, Мангилик Ел 10" in values
    assert "7001112233" in values and "+77001112233" in values
    assert "7012223344" in values


def test_exact_names_are_replaced_regardless_of_case():
    text = "Айжан Нурланова спрашивает, а айжан нурланова ждёт ответа"
    masked = mask_known(text, buyer_values(FAKE_ORDERS))
    assert "нурланова" not in masked.lower()
    assert masked.count(MASK_BUYER) == 2


def test_phone_in_any_format_is_masked_with_known_values():
    text = "Звонить 8 701 222 33 44 или +7 700 111 22 33"
    masked = mask_text(mask_known(text, buyer_values(FAKE_ORDERS)))
    assert "701" not in masked and "700" not in masked


def test_unknown_names_are_not_touched():
    text = "Прибыль за неделю по товару D007"
    assert mask_known(text, buyer_values(FAKE_ORDERS)) == text


def test_short_values_do_not_mask_words():
    # короткие значения не заменяем, иначе испортим обычный текст
    assert mask_known("Да, ок", ["Да", "ок"]) == "Да, ок"


def test_question_to_ai_is_masked_by_known_buyer_names(client, demo, monkeypatch):
    from sqlalchemy import select
    from sqlalchemy.orm import Session as DbSession

    from app.db import engine
    from app.models import AITurn

    monkeypatch.setattr(ai, "buyer_values_for_shop", lambda db, shop_id: buyer_values(FAKE_ORDERS))
    client.post("/v1/ai/consent", headers=demo["headers"], json={"granted": True})
    r = client.post(f"/v1/shops/{demo['shop_id']}/ai/ask", headers=demo["headers"],
                    json={"question": "Айжан Нурланова спрашивает, сколько прибыли по её заказу за 7 дней?"})
    assert r.status_code == 200, r.text
    with DbSession(engine) as db:
        stored = db.scalars(select(AITurn).where(AITurn.shop_id == demo["shop_id"])).all()[-1].question
    assert "Нурланова" not in stored
    assert MASK_BUYER in stored
