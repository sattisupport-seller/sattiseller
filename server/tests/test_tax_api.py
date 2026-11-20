"""Налог через API (ТЗ 2.1, раздел 7): ставка, валидация, строка «Налог» в прибыли."""


def _tax_post(client, demo, body):
    return client.post(f"/v1/shops/{demo['shop_id']}/tax", json=body, headers=demo["headers"])


def _steps(client, demo, period="90d"):
    r = client.get(f"/v1/shops/{demo['shop_id']}/profit-breakdown?period={period}", headers=demo["headers"])
    assert r.status_code == 200, r.text
    return r.json()


def test_tax_off_by_default(client, demo):
    r = client.get(f"/v1/shops/{demo['shop_id']}/tax", headers=demo["headers"])
    assert r.status_code == 200
    assert r.json()["current"] is None
    body = _steps(client, demo)
    assert all(s["key"] != "tax" for s in body["steps"])
    assert "до налогов" in body["note"]


def test_tax_rate_adds_tax_step_and_note(client, demo):
    r = _tax_post(client, demo, {"enabled": True, "rate_percent": "4"})
    assert r.status_code == 201, r.text
    assert r.json()["rate_bp"] == 400

    body = _steps(client, demo)
    tax_steps = [s for s in body["steps"] if s["key"] == "tax"]
    assert len(tax_steps) == 1
    assert tax_steps[0]["label"] == "Налог (4%)"
    assert tax_steps[0]["minor"] < 0
    assert "после налога" in body["note"]

    # лесенка сходится: чистые продажи − себестоимость − комиссия − доставка − налог = прибыль по товарам
    s = {x["key"]: x["minor"] for x in body["steps"]}
    assert s["net_sales"] + s["cost"] + s["commission"] + s["delivery"] + s["tax"] == s["product_profit"]


def test_half_percent_accepted_and_comma_decimal(client, demo):
    r = _tax_post(client, demo, {"enabled": True, "rate_percent": "1,5"})
    assert r.status_code == 201, r.text
    assert r.json()["rate_bp"] == 150
    body = _steps(client, demo)
    assert [s["label"] for s in body["steps"] if s["key"] == "tax"] == ["Налог (1,5%)"]


def test_disabling_tax_removes_tax_step(client, demo):
    _tax_post(client, demo, {"enabled": True, "rate_percent": "4"})
    r = _tax_post(client, demo, {"enabled": False})
    assert r.status_code == 201
    assert r.json()["enabled"] is False
    body = _steps(client, demo)
    assert all(s["key"] != "tax" for s in body["steps"])


def test_invalid_rates_rejected(client, demo):
    assert _tax_post(client, demo, {"enabled": True, "rate_percent": "4,55"}).status_code == 422
    assert _tax_post(client, demo, {"enabled": True, "rate_percent": "31"}).status_code == 422
    assert _tax_post(client, demo, {"enabled": True, "rate_percent": "abc"}).status_code == 422
    assert _tax_post(client, demo, {"enabled": True}).status_code == 422


def test_history_versions_listed_newest_first(client, demo):
    _tax_post(client, demo, {"enabled": True, "rate_percent": "4", "effective_from": "2026-01-01"})
    _tax_post(client, demo, {"enabled": True, "rate_percent": "6", "effective_from": "2026-06-01"})
    r = client.get(f"/v1/shops/{demo['shop_id']}/tax", headers=demo["headers"])
    items = r.json()["items"]
    assert [i["rate_bp"] for i in items] == [600, 400]
    assert r.json()["current"]["rate_bp"] == 600


def _ask(client, demo, question):
    r = client.post(f"/v1/shops/{demo['shop_id']}/ai/ask", json={"question": question}, headers=demo["headers"])
    assert r.status_code == 200, r.text
    return r.json()


def test_ai_tax_question_without_rate_offers_settings(client, demo):
    client.post("/v1/ai/consent", headers=demo["headers"], json={"granted": True})
    body = _ask(client, demo, "Сколько налога было за прошлый месяц?")
    assert "Ставка налога не задана" in body["renderedAnswer"]
    assert any(a["type"] == "open_tax_settings" for a in body["suggestedActions"])


def test_ai_tax_question_with_rate_gives_amount(client, demo):
    client.post("/v1/ai/consent", headers=demo["headers"], json={"granted": True})
    _tax_post(client, demo, {"enabled": True, "rate_percent": "4"})
    body = _ask(client, demo, "Сколько налога было за прошлый месяц?")
    assert "Ставка налога не задана" not in body["renderedAnswer"]
    assert "налог —" in body["renderedAnswer"]


def test_ai_previous_week_is_monday_to_sunday(client, demo):
    from datetime import date

    client.post("/v1/ai/consent", headers=demo["headers"], json={"granted": True})
    body = _ask(client, demo, "Сколько я заработал на прошлой неделе?")
    start = date.fromisoformat(body["period"]["from"])
    end = date.fromisoformat(body["period"]["to"])
    assert start.weekday() == 0
    assert end.weekday() == 6
    assert (end - start).days == 6
