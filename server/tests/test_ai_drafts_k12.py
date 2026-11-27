"""Черновики карточки (К-12, 22.11): обрезка заголовков по слову, никогда внутри числа; согласие до черновика."""

import re

from app.ai import _short_title, product_draft


def test_short_title_never_cuts_inside_a_number():
    for head_len in range(50, 66):
        head = ("а" * head_len)[:head_len]
        text = head + " 2024 года"
        title = _short_title(text)
        assert len(title) <= 60
        assert not re.search(r"\d+$", title) or re.search(r"\d+$", title).group(0) == "2024", (head_len, title)


def test_short_title_cuts_on_word_boundary():
    title = _short_title("Термокружка стальная, ручка, " + "а" * 20 + " 2024 года выпуска для дома и кухни")
    assert title == "Термокружка стальная, ручка, " + "а" * 20 + " 2024 года"


def test_short_title_keeps_short_text_as_is():
    assert _short_title("Чашка 2024 года, белая") == "Чашка 2024 года, белая"


def test_draft_with_number_near_sixtieth_char_is_not_rejected():
    facts = "Термокружка стальная, ручка, " + "а" * 31 + "2024 года\nобъём 350 мл\nцвет: белый"
    out = product_draft(facts, "ru", 0)
    assert all(len(t) <= 60 for t in out["titles"])
    for t in out["titles"]:
        assert "20" not in re.findall(r"\d+", t) or "2024" in facts


def test_draft_works_without_separate_consent(client, demo):
    """К-24: отдельного согласия на ИИ нет — карточка работает сразу."""
    r = client.post("/v1/ai/product-drafts", headers=demo["headers"],
                    data={"shop_id": demo["shop_id"], "facts": "Чашка белая", "languages": "ru"})
    assert r.status_code == 201, r.text


def test_draft_with_long_number_line_works_end_to_end(client, demo):
    client.post("/v1/ai/consent", headers=demo["headers"], json={"granted": True})
    head = "Термокружка стальная, ручка, " + "а" * 31
    facts = head + "2024 года\nобъём 350 мл"
    r = client.post("/v1/ai/product-drafts", headers=demo["headers"],
                    data={"shop_id": demo["shop_id"], "facts": facts, "languages": "ru"})
    assert r.status_code == 201, r.text
    assert all(len(t) <= 60 for t in r.json()["titles"])
