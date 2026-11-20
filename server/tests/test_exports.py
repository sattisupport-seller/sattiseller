"""Выгрузки (ТЗ 2.1, раздел 9.4 и 9.5): Excel-отчёт о прибыли и «Скачать мои данные»."""

import io
import json
import zipfile
from decimal import Decimal

from openpyxl import load_workbook

from app.exports import _cell
from tests.conftest import login


def _xlsx(client, demo, period="90d"):
    r = client.get(f"/v1/shops/{demo['shop_id']}/exports/profit.xlsx?period={period}", headers=demo["headers"])
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("application/vnd.openxmlformats")
    assert "satti-pribyl-" in r.headers["content-disposition"]
    return load_workbook(io.BytesIO(r.content), data_only=True)


def test_profit_xlsx_has_expected_sheets(client, demo):
    wb = _xlsx(client, demo)
    assert wb.sheetnames == ["Сводка", "Товары", "Заказы", "Не хватает данных"]


def test_profit_xlsx_totals_match_screen(client, demo):
    wb = _xlsx(client, demo)
    screen = client.get(f"/v1/shops/{demo['shop_id']}/profit-breakdown?period=90d", headers=demo["headers"]).json()
    summary = {row[0].value: row[1].value for row in wb["Сводка"].iter_rows(min_row=6) if row[0].value}
    for step in screen["steps"]:
        # тиыны → тенге без потери точности
        assert Decimal(str(summary[step["label"]])) * 100 == Decimal(step["minor"]), step["label"]


def test_profit_xlsx_money_is_exact_tiyn(client, demo):
    wb = _xlsx(client, demo)
    values = [c.value for row in wb["Товары"].iter_rows(min_row=2) for c in row[3:9] if isinstance(c.value, (int, float, Decimal))]
    assert values
    for v in values:
        assert Decimal(str(v)) * 100 == int(Decimal(str(v)) * 100)


def test_formula_like_text_is_escaped():
    assert _cell("=SUM(A1)") == "'=SUM(A1)"
    assert _cell("+7 777") == "'+7 777"
    assert _cell("-minus") == "'-minus"
    assert _cell("@cmd") == "'@cmd"
    assert _cell("Обычный текст") == "Обычный текст"
    assert _cell(12) == 12


def test_demo_cannot_export_account_data(client, demo):
    r = client.get("/v1/me/export", headers=demo["headers"])
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "account_required"


def test_my_data_zip_contents_and_daily_limit(client):
    tokens = login(client, "exporter@example.com")
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    from tests.conftest import confirm_age
    confirm_age(client, headers)
    created = client.post("/v1/shops", headers=headers,
                          json={"name": "Мой магазин", "timezone": "Asia/Almaty", "language": "ru"})
    assert created.status_code == 201, created.text

    for _ in range(3):
        r = client.get("/v1/me/export", headers=headers)
        assert r.status_code == 200, r.text
        assert r.headers["content-type"] == "application/zip"
    names = set(zipfile.ZipFile(io.BytesIO(r.content)).namelist())
    assert names == {"profile.json", "shop.xlsx", "assistant.json", "consents.json", "subscription.json"}

    z = zipfile.ZipFile(io.BytesIO(r.content))
    profile = json.loads(z.read("profile.json"))
    assert profile["email"] == "exporter@example.com"
    assert [s["name"] for s in profile["shops"]] == ["Мой магазин"]
    shop_wb = load_workbook(io.BytesIO(z.read("shop.xlsx")))
    assert shop_wb.sheetnames == ["Товары", "Затраты", "Заказы", "Возвраты", "Комиссии", "Расходы", "Налог"]

    limited = client.get("/v1/me/export", headers=headers)
    assert limited.status_code == 429
