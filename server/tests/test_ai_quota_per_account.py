"""К-21 (решение владельца 23.11.2026, 01:53): все устройства — один аккаунт. Дневной лимит помощника, бюджет и история
считаются на аккаунт, а не на устройство: 10 запросов на одном телефоне — на другом остаётся 20."""

from app.config import settings
from tests.conftest import confirm_age, login

ASK = {"question": "Когда доставка?", "tone": "polite"}


def _device(client, email):
    """Новый вход — новое устройство (отдельная сессия и токены)."""
    tokens = login(client, email)
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def test_daily_limit_is_shared_between_devices(client, monkeypatch, live_reply_ok):
    monkeypatch.setattr(settings, "billing_enforced", False)
    phone_a = _device(client, "quota-two@example.com")
    confirm_age(client, phone_a)
    shop_id = client.post("/v1/shops", headers=phone_a, json={"name": "Магазин"}).json()["id"]
    phone_b = _device(client, "quota-two@example.com")
    assert phone_a != phone_b

    for _ in range(10):
        assert client.post("/v1/ai/reply-drafts", params={"shop_id": shop_id}, headers=phone_a, json=ASK).status_code == 201
    left_a = client.get(f"/v1/ai/quota?shop_id={shop_id}", headers=phone_a).json()["remaining"]
    left_b = client.get(f"/v1/ai/quota?shop_id={shop_id}", headers=phone_b).json()["remaining"]
    assert left_a == left_b  # тот же остаток на обоих телефонах
    assert settings.ai_daily_limit == 30
    # /ai/quota отвечает «сколько останется после следующего запроса»: 30 − 10 − 1
    assert left_b == settings.ai_daily_limit - 10 - 1


def test_limit_reached_on_one_device_blocks_the_other(client, monkeypatch, live_reply_ok):
    monkeypatch.setattr(settings, "billing_enforced", False)
    monkeypatch.setattr(settings, "ai_daily_limit", 3)
    phone_a = _device(client, "quota-block@example.com")
    confirm_age(client, phone_a)
    shop_id = client.post("/v1/shops", headers=phone_a, json={"name": "Магазин"}).json()["id"]
    phone_b = _device(client, "quota-block@example.com")
    assert client.post("/v1/ai/reply-drafts", params={"shop_id": shop_id}, headers=phone_a, json=ASK).status_code == 201
    assert client.post("/v1/ai/reply-drafts", params={"shop_id": shop_id}, headers=phone_b, json=ASK).status_code == 201
    assert client.post("/v1/ai/reply-drafts", params={"shop_id": shop_id}, headers=phone_a, json=ASK).status_code == 201
    r = client.post("/v1/ai/reply-drafts", params={"shop_id": shop_id}, headers=phone_b, json=ASK)
    # К-35: лимит исчерпан на одном телефоне — на другом ответ уже по шаблону с пометкой
    assert r.status_code == 201 and r.json()["generatedBy"] == "template" and "лимит" in r.json()["warnings"][0]


def test_assistant_history_is_shared_between_devices(client, monkeypatch):
    monkeypatch.setattr(settings, "billing_enforced", False)
    phone_a = _device(client, "quota-hist@example.com")
    confirm_age(client, phone_a)
    shop_id = client.post("/v1/shops", headers=phone_a, json={"name": "Магазин"}).json()["id"]
    phone_b = _device(client, "quota-hist@example.com")
    asked = client.post(f"/v1/shops/{shop_id}/ai/ask", headers=phone_a, json={"question": "Сколько заказов вчера?"})
    assert asked.status_code == 200, asked.text
    convs = client.get(f"/v1/ai/conversations?shop_id={shop_id}", headers=phone_b)
    assert convs.status_code == 200
    assert asked.json()["conversationId"] in {c["id"] for c in convs.json()["items"]}
