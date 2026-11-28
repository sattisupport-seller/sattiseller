"""К-33 Б1: сверка с выгрузкой Kaspi Pay «Продажи» — синтетический файл (формат — по подсказкам заголовков)."""

import io
from datetime import datetime, timedelta, timezone

import pytest
from openpyxl import Workbook
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.config import settings
from app.db import engine
from app.errors import ApiError
from app.kaspi_pay import find_columns, money_minor
from app.models import KaspiPayRow
from tests.test_e2e_profit_by_hand import _order
from tests.test_seller_access import _connect, _seller, env  # noqa: F401 — фикстура Kaspi на моке

T = 100


def _xlsx(header, rows) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.append(header)
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _shop(client, env, monkeypatch):  # noqa: F811
    """Магазин из ручной сверки К-30/К-33 А2: A-1 — 10 000 ₸, комиссия 12,5 % = 1 250 ₸, доставка 580 ₸;
    B-1 — рассрочка, 8 000 ₸, комиссия 13 % = 1 040 ₸, доставки нет."""
    monkeypatch.setattr(settings, "billing_enforced", False)
    headers, shop_id = _seller(client, "pay-b1@example.com")
    assert _connect(client, headers, shop_id, seller="PAY-1").status_code == 201
    created = datetime.now(timezone.utc) - timedelta(days=4)
    _order(env, "A-1", created, "COMPLETED", [{"id": "EA1", "idx": 0, "qty": 2, "basePrice": 5000}], seller_delivery=500)
    _order(env, "B-1", created, "COMPLETED", [{"id": "EB1", "idx": 1, "qty": 1, "basePrice": 8000}], credit=True)
    assert client.post(f"/v1/shops/{shop_id}/kaspi/sync", headers=headers).status_code == 200
    assert client.post(f"/v1/shops/{shop_id}/commissions", headers=headers,
                       json={"category": "Посуда для кухни", "rate_percent": "12,5"}).status_code == 201
    return headers, shop_id


def _upload(client, headers, shop_id, data: bytes, name="sales.xlsx"):
    return client.post(f"/v1/shops/{shop_id}/kaspi/pay-report", headers=headers,
                       files={"file": (name, data, "application/octet-stream")})


def test_reconciliation_matches_mismatches_and_missing(client, env, monkeypatch):  # noqa: F811
    headers, shop_id = _shop(client, env, monkeypatch)
    data = _xlsx(["Дата", "Номер заказа", "Сумма заказа", "Комиссия", "Доставка", "К выплате"], [
        ["2026-11-24", "A-1", 10000, -1250, -580, 8170],
        ["2026-11-24", "B-1", 7900, -1040, 0, 6860],  # Kaspi: на 100 ₸ меньше
        ["2026-11-25", "X-9", 3000, -375, 0, 2625],  # заказа нет у нас
        ["2026-11-25", "", "мусор", None, None, None],  # непонятная строка
    ])
    r = _upload(client, headers, shop_id, data)
    assert r.status_code == 200, r.text
    res = r.json()
    assert res["orders_in_file"] == 3 and res["matched"] == 1
    assert res["mismatch_orders"] == 1 and res["mismatch_sum_minor"] == 100 * T  # «расхождение 100 ₸ по 1 заказу»
    m = res["mismatches"][0]
    assert m["order_number"] == "B-1" and m["field"] == "amount" and m["diff_minor"] == -100 * T
    assert res["missing_in_satti"] == ["X-9"] and res["bad_rows"] == [5]
    assert res["columns"]["order"] == "Номер заказа" and res["columns"]["payout"] == "К выплате"
    with DbSession(engine) as db:
        rows = {r.order_number: r for r in db.scalars(select(KaspiPayRow).where(KaspiPayRow.shop_id == shop_id))}
    assert set(rows) == {"A-1", "B-1", "X-9"}
    assert rows["A-1"].commission_minor == 1250 * T and rows["A-1"].payout_minor == 8170 * T

    # повторная загрузка заменяет строки заказа, а не дублирует
    data2 = _xlsx(["Номер заказа", "Сумма"], [["B-1", 8000]])
    res2 = _upload(client, headers, shop_id, data2).json()
    assert res2["matched"] == 1 and res2["mismatch_orders"] == 0
    with DbSession(engine) as db:
        assert len(db.scalars(select(KaspiPayRow).where(KaspiPayRow.order_number == "B-1")).all()) == 1


def test_return_rows_are_summed_with_their_order(client, env, monkeypatch):  # noqa: F811
    headers, shop_id = _shop(client, env, monkeypatch)
    data = _xlsx(["№ заказа", "Сумма операции"], [["A-1", 10000], ["A-1", 4000], ["A-1", -4000]])
    res = _upload(client, headers, shop_id, data).json()
    assert res["matched"] == 1 and res["mismatch_orders"] == 0


def test_csv_with_spaces_and_tenge_sign(client, env, monkeypatch):  # noqa: F811
    headers, shop_id = _shop(client, env, monkeypatch)
    csv = "Номер заказа;Сумма заказа;Комиссия\r\nA-1;10 000,00 ₸;−1 250 ₸\r\n".encode("utf-8-sig")
    res = _upload(client, headers, shop_id, csv, name="sales.csv").json()
    assert res["matched"] == 1, res


def test_missing_columns_error_lists_file_headers():
    with pytest.raises(ApiError) as e:
        find_columns(["Дата", "Покупатель", "Итого"])
    assert "номер заказа" in e.value.message and "«Покупатель»" in e.value.message


def test_money_parsing():
    assert money_minor(10000) == 1_000_000
    assert money_minor(12345.5) == 1_234_550
    assert money_minor("12 345,50 ₸") == 1_234_550
    assert money_minor("−1 000") == -100_000
    assert money_minor("(1 000)") == -100_000
    assert money_minor("") is None and money_minor(None) is None
    with pytest.raises(ValueError):
        money_minor("мусор")


def test_needs_login(client):
    assert client.post("/v1/shops/x/kaspi/pay-report", files={"file": ("a.xlsx", b"x")}).status_code in (401, 403)
