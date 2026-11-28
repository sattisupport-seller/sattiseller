"""К-33 А2: тарифы 2026 в отчётах о прибыли — плательщик и неплательщик НДС, доставка Kaspi с НДС."""

from app.finance import Return, SaleLine, calc_line, sale_result
from app.kaspi_tariffs import net_rate_bp, with_vat, without_vat


def _line(**kw):
    base = dict(qty=1, unit_price_minor=1_000_000, status="completed", unit_cost_minor=600_000,
                buyer_delivery_minor=with_vat(69_900), commission_rate_bp=1250)
    base.update(kw)
    return SaleLine(**base)


def test_non_payer_pays_commission_and_delivery_with_vat():
    s = sale_result(_line())
    assert s.gross_minor == 1_000_000
    assert s.commission_minor == 125_000  # 12,5 % с НДС
    assert s.delivery_minor == 81_084  # 699 ₸ × 1,16
    assert s.profit_minor == 1_000_000 - 600_000 - 125_000 - 81_084


def test_payer_revenue_without_vat_commission_net_rate_delivery_without_vat():
    s = sale_result(_line(vat_payer=True))
    assert s.gross_minor == without_vat(1_000_000) == 862_069
    assert s.commission_minor == 109_000  # 10,9 % без НДС — по таблице Kaspi, а не 12,5 / 1,16
    assert s.delivery_minor == 69_900
    assert s.profit_minor == 862_069 - 600_000 - 109_000 - 69_900


def test_payer_tax_is_on_revenue_without_vat():
    s = sale_result(_line(vat_payer=True, tax_rate_bp=400))
    assert s.tax_minor == 34_483  # 4 % от 8 620,69 ₸


def test_payer_promo_rate_uses_promo_net_rate():
    s = sale_result(_line(vat_payer=True, commission_rate_bp=1300))
    assert s.commission_minor == 1_000_000 * net_rate_bp(1300) // 10_000 == 113_400


def test_cancelled_order_has_no_delivery_and_no_commission():
    r = calc_line(_line(status="cancelled"))
    assert r.profit_minor == 0 and r.net_sales_minor == 0


def test_return_after_delivery_keeps_delivery_cost():
    ret = Return(returned_qty=1, refund_minor=1_000_000, commission_returned_minor=125_000,
                 delivery_returned_minor=0, reverse_delivery_minor=0, goods_sellable=True)
    r = calc_line(_line(returns=[ret]))
    assert r.net_sales_minor == 0
    assert r.profit_minor == -with_vat(69_900)  # товар вернулся, комиссия вернулась, доставка — расход продавца


def test_vat_payer_switch_changes_shop_reports(client, demo):
    shop = f"/v1/shops/{demo['shop_id']}"
    before = client.get(f"{shop}/profit-breakdown?period=30d", headers=demo["headers"]).json()
    r = client.patch(shop, json={"vat_payer": True}, headers=demo["headers"])
    assert r.status_code == 200 and r.json()["vat_payer"] is True
    after = client.get(f"{shop}/profit-breakdown?period=30d", headers=demo["headers"]).json()
    steps_b = {s["key"]: s["minor"] for s in before["steps"]}
    steps_a = {s["key"]: s["minor"] for s in after["steps"]}
    assert steps_a["net_sales"] < steps_b["net_sales"]  # выручка без НДС
    assert steps_a["commission"] > steps_b["commission"]  # минус меньше: комиссия без НДС
    # демо: остальные настройки магазина менять нельзя
    assert client.patch(shop, json={"name": "x"}, headers=demo["headers"]).status_code == 403
    assert client.patch(shop, json={"vat_payer": False}, headers=demo["headers"]).json()["vat_payer"] is False
