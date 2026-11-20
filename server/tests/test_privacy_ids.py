"""AUD-19: ИИН и номера банковских карт маскируются до передачи ИИ и записи в журнал."""

from app.privacy import contains_pii, mask_text


def test_iin_is_masked():
    out = mask_text("Покупатель с ИИН 880101300123 вернул товар")
    assert "880101300123" not in out
    assert "[ИИН]" in out


def test_valid_card_number_is_masked_in_all_spacing_forms():
    # 4111 1111 1111 1111 — тестовый номер, проходит проверку Луна
    for text in ("карта 4111111111111111", "карта 4111 1111 1111 1111", "карта 4111-1111-1111-1111"):
        out = mask_text(text)
        assert "4111" not in out, text
        assert "[карта]" in out


def test_number_that_fails_luhn_is_not_masked_as_card():
    out = mask_text("номер 4111 1111 1111 1112")
    assert "[карта]" not in out
    assert "4111 1111 1111 1112" in out


def test_order_numbers_and_amounts_are_untouched():
    text = "Заказ 12345678 на сумму 150000 ₸, 2 штуки, телефон +7 701 123 45 67"
    out = mask_text(text)
    assert "12345678" in out
    assert "150000" in out
    assert "[телефон]" in out  # телефон по-прежнему маскируется


def test_pii_detection_sees_iin():
    assert contains_pii("ИИН 880101300123")
    assert not contains_pii("заказ 12345")
