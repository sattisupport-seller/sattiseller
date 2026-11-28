"""К-30 п.2, пересчитано в К-33 А2: прибыль, сверенная вручную до тенге (docs/FEATURE_CHECK.md, «Ручная сверка прибыли»).

Kaspi (мок): три заказа. Продавец не плательщик НДС. Комиссия категории 12,5 % с НДС (основная группа 2026),
рассрочка 0-0-24 — 13,0 % с НДС (ставка по умолчанию), налог 3 %, себестоимость K0 = 2 000 ₸, K1 = 3 000 ₸.
Доставка Kaspi: deliveryCostForSeller = 500 ₸ без НДС → продавцу списывается 580 ₸ с НДС 16 %.
  A: выдан, 2 × K0 по 5 000 ₸, доставка 580 ₸ → 10 000 − 4 000 − 1 250 − 580 − 300 = 3 870 ₸
  B: выдан, рассрочка, 1 × K1 за 8 000 ₸ → 8 000 − 3 000 − 1 040 − 0 − 240 = 3 720 ₸
  C: возвращён на склад, 1 × K0 за 5 000 ₸ → продажа 5 000 − 2 000 − 625 − 150 = 2 225 ₸,
     возврат −5 000 + 2 000 + 625 + 150 = −2 225 ₸ → 0 ₸
Итог: 7 590 ₸; чистые продажи 23 000 − 5 000 = 18 000 ₸.
"""

from datetime import datetime, timedelta, timezone

from tests.kaspi_mock import DAY_MS
from tests.test_seller_access import _connect, _seller, env  # noqa: F401 — фикстура Kaspi на моке

T = 100  # тиынов в тенге


def _order(mock, code, created, state, rows, credit=False, seller_delivery=None, to_warehouse=None):
    ms = int(created.timestamp() * 1000)
    mock.entries[code] = rows
    attrs = {"state": state, "creationDate": ms, "completedDate": ms + DAY_MS,
             "paymentMode": "PAY_WITH_CREDIT" if credit else "PREPAID"}
    if seller_delivery is not None:
        attrs["deliveryCostForSeller"] = seller_delivery
    if to_warehouse is not None:
        attrs["returnedToWarehouse"] = to_warehouse
    mock.orders.append({"id": code, "type": "orders", "attributes": attrs,
                        "relationships": {"entries": {"links": {"related": f"/orders/{code}/entries"}}}})


def test_profit_matches_hand_calculation_to_the_tenge(client, env, monkeypatch):  # noqa: F811
    from app.config import settings

    monkeypatch.setattr(settings, "billing_enforced", False)  # расчёт прибыли; подписка — отдельные тесты
    headers, shop_id = _seller(client, "e2e-hand@example.com")
    assert _connect(client, headers, shop_id, seller="HAND-1").status_code == 201
    created = datetime.now(timezone.utc) - timedelta(days=4)
    _order(env, "A-1", created, "COMPLETED", [{"id": "EA1", "idx": 0, "qty": 2, "basePrice": 5000}], seller_delivery=500)
    _order(env, "B-1", created, "COMPLETED", [{"id": "EB1", "idx": 1, "qty": 1, "basePrice": 8000}], credit=True)
    _order(env, "C-1", created, "RETURNED", [{"id": "EC1", "idx": 0, "qty": 1, "basePrice": 5000}], to_warehouse=True)
    assert client.post(f"/v1/shops/{shop_id}/kaspi/sync", headers=headers).status_code == 200

    products = {p["sku"]: p["product_id"] for p in client.get(f"/v1/shops/{shop_id}/products/missing-costs",
                                                             headers=headers).json()["items"]}
    assert set(products) == {"K0", "K1"}
    r = client.post(f"/v1/shops/{shop_id}/cost-versions/bulk", headers=headers, json={"items": [
        {"product_id": products["K0"], "purchase": "2000", "stock_qty": 10},
        {"product_id": products["K1"], "purchase": "3000", "stock_qty": 5}], "apply_to_history": True})
    assert r.status_code == 200, r.text
    assert client.post(f"/v1/shops/{shop_id}/commissions", headers=headers,
                       json={"category": "Посуда для кухни", "rate_percent": "12,5"}).status_code == 201
    assert client.post(f"/v1/shops/{shop_id}/tax", headers=headers,
                       json={"enabled": True, "rate_percent": "3"}).status_code == 201

    kpi = client.get(f"/v1/shops/{shop_id}/overview?period=30d", headers=headers).json()["kpi"]
    assert kpi["coverage_bp"] == 10000, kpi  # все строки посчитаны полностью
    assert kpi["profit_minor"] == 7590 * T, kpi
    assert kpi["net_sales_minor"] == 18000 * T, kpi
