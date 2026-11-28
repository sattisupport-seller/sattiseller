"""К-33 А5: главный экран языком денег — утечки маржи, минимальная цена без убытка, порог доставки, отмены."""

from app.insights import _min_price_fixed_delivery
from app.kaspi_tariffs import threshold_hint, unit_profit


def _money(client, demo):
    r = client.get(f"/v1/shops/{demo['shop_id']}/money", headers=demo["headers"])
    assert r.status_code == 200, r.text
    return r.json()


def test_leaks_losing_first_with_month_total(client, demo):
    m = _money(client, demo)
    leaks = m["leaks"]
    assert leaks["count"] >= 1 and leaks["losing_count"] >= 1
    profits = [i["profit_minor"] for i in leaks["items"]]
    assert profits == sorted(profits)  # убыточные сверху
    losing = [p for p in profits if p < 0]
    assert leaks["month_loss_minor"] == -sum(losing) > 0  # «за месяц вы теряете N ₸ на M товарах»
    for item in leaks["items"]:
        assert item["margin_bp"] is None or item["profit_minor"] < 0 or item["margin_bp"] <= leaks["near_zero_bp"]
        assert item["worst_rate_bp"] == 1300  # худшая ставка — акция 0-0-24 основной группы
        if item["profit_minor"] < 0:
            assert item["min_price_minor"] > item["avg_price_minor"]  # чтобы выйти из минуса, цену надо поднять


def test_min_price_is_the_first_price_without_loss():
    for cost, delivery in [(124_500, 38_793), (190_000, 0), (5_000, 12_000)]:
        for vat in (False, True):
            p = _min_price_fixed_delivery(cost, 1300, delivery, vat, 300)
            assert unit_profit(p, cost, 1300, vat_payer=vat, tax_bp=300, delivery_tariff_minor=delivery).profit_minor >= 0
            assert unit_profit(p - 100, cost, 1300, vat_payer=vat, tax_bp=300,
                               delivery_tariff_minor=delivery).profit_minor < 0


def test_threshold_hint_matches_coordinator_example():
    """5 200 ₸ вместо 4 990 ₸ при комиссии 12,5 % — продавец получает примерно на 400 ₸ меньше с заказа."""
    h = threshold_hint(520_000, 300_000, 1250)
    assert h is not None and h.threshold_tenge == 5_000 and h.suggested_price_minor == 499_000
    assert 35_000 <= h.gain_minor <= 45_000


def test_cancel_protection_share_and_limit(client, demo):
    cp = _money(client, demo)["cancel_protection"]
    assert cp["kaspi_limit_bp"] == 300
    assert cp["cancel_share_bp"] == round(cp["cancelled_count"] * 10_000 / cp["orders_count"])
    assert "штраф" not in cp["note"]  # денежного штрафа в правилах Kaspi нет


def test_vat_payer_changes_money_screen(client, demo):
    before = _money(client, demo)
    client.patch(f"/v1/shops/{demo['shop_id']}", json={"vat_payer": True}, headers=demo["headers"])
    after = _money(client, demo)
    assert after["vat_payer"] is True and before["vat_payer"] is False
    b = {i["product_id"]: i["min_price_minor"] for i in before["leaks"]["items"]}
    a = {i["product_id"]: i["min_price_minor"] for i in after["leaks"]["items"]}
    common = set(a) & set(b)
    assert all(a[p] != b[p] for p in common)  # расчёт без НДС — другая минимальная цена
    assert before["leaks"]["month_loss_minor"] != after["leaks"]["month_loss_minor"]
