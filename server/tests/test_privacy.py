"""Маскировка данных покупателей для ИИ (ADR-0004)."""

import pytest

from app.privacy import MASK_ADDRESS, MASK_EMAIL, MASK_FIELD, MASK_PHONE, contains_pii, mask_obj, mask_text


@pytest.mark.parametrize("raw", [
    "+7 708 206 04 03",
    "+77082060403",
    "8 (708) 206-04-03",
    "87082060403",
    "+7 (708) 206 04 03",
])
def test_phone_formats_are_masked(raw):
    assert mask_text(f"Звонил {raw}, спросите") == f"Звонил {MASK_PHONE}, спросите"


def test_email_is_masked():
    assert mask_text("пишите на ivan.petrov@mail.ru сегодня") == f"пишите на {MASK_EMAIL} сегодня"


def test_address_is_masked_up_to_sentence_end():
    text = "Доставить на ул. Абая 15, кв. 8. Спасибо"
    masked = mask_text(text)
    assert "Абая" not in masked
    assert "15" not in masked
    assert MASK_ADDRESS in masked
    assert masked.endswith("Спасибо")


def test_numbers_that_are_not_phones_are_kept():
    # суммы, даты и артикулы не трогаем
    text = "Продано 12 шт. на 150 000 ₸ 01.11.2026, артикул D007"
    assert mask_text(text) == text


def test_buyer_fields_are_hidden_by_key():
    obj = {"sku": "D001", "buyer_name": "Айжан Нурланова", "buyer_phone": "+77001112233", "qty": 2}
    masked = mask_obj(obj)
    assert masked == {"sku": "D001", "buyer_name": MASK_FIELD, "buyer_phone": MASK_FIELD, "qty": 2}


def test_nested_values_are_masked():
    obj = {"order": {"note": "Звоните +7 701 000 00 00", "items": [{"sku": "D002", "email": "a@b.kz"}]}}
    masked = mask_obj(obj)
    assert masked["order"]["note"] == f"Звоните {MASK_PHONE}"
    assert masked["order"]["items"][0] == {"sku": "D002", "email": MASK_FIELD}


def test_masking_is_idempotent():
    once = mask_text("тел +7 701 000 00 00, mail x@y.kz")
    assert mask_text(once) == once


def test_contains_pii_flags_only_real_pii():
    assert contains_pii("мой номер 87010000000")
    assert contains_pii("почта a@b.kz")
    assert not contains_pii("прибыль за 7 дней 150 000 ₸")


def test_question_is_stored_without_personal_data(client, demo):
    from sqlalchemy import select
    from sqlalchemy.orm import Session as DbSession

    from app.db import engine
    from app.models import AITurn

    client.post("/v1/ai/consent", headers=demo["headers"], json={"granted": True})
    r = client.post(f"/v1/shops/{demo['shop_id']}/ai/ask", headers=demo["headers"],
                    json={"question": "Покупатель +7 701 000 00 00 живёт на ул. Абая 15, почта a@b.kz. Сколько прибыли за 7 дней?"})
    assert r.status_code == 200, r.text
    with DbSession(engine) as db:
        turns = db.scalars(select(AITurn).where(AITurn.shop_id == demo["shop_id"])).all()
        assert turns
        stored = turns[-1].question
    assert "701" not in stored
    assert "Абая" not in stored
    assert "a@b.kz" not in stored
    assert MASK_PHONE in stored and MASK_EMAIL in stored


def test_reply_draft_warns_and_masks(client, demo):
    client.post("/v1/ai/consent", headers=demo["headers"], json={"granted": True})
    r = client.post(f"/v1/ai/reply-drafts?shop_id={demo['shop_id']}", headers=demo["headers"],
                    json={"question": "Перезвоните на 87010000000", "tone": "polite"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert any("личные данные" in w for w in body["warnings"])
    assert "87010000000" not in body["reply"]
