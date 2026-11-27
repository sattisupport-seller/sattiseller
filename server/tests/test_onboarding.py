"""К-21, часть 2, п.6: обязательное обучение после регистрации — отметка у аккаунта (второе устройство не повторяет),
без обучения подключение Kaspi недоступно, порог возобновления — настройка сервера."""

from app.config import settings
from tests.conftest import confirm_age, login
from tests.test_seller_access import _connect, env  # noqa: F401 — фикстура Kaspi на моке


def _account(client, email):
    tokens = login(client, email)
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    confirm_age(client, headers)
    shop_id = client.post("/v1/shops", headers=headers, json={"name": "Магазин"}).json()["id"]
    return headers, shop_id


def test_kaspi_is_closed_until_onboarding_done(client, env):  # noqa: F811
    headers, shop_id = _account(client, "onb1@example.com")
    assert client.get("/v1/me", headers=headers).json()["onboarding_done"] is False
    r = _connect(client, headers, shop_id, seller="ONB-1")
    assert r.status_code == 403 and r.json()["error"]["code"] == "onboarding_required"
    assert client.post("/v1/me/onboarding/complete", headers=headers).json() == {"onboarding_done": True}
    assert _connect(client, headers, shop_id, seller="ONB-1").status_code == 201


def test_done_on_one_device_is_not_repeated_on_another(client):
    phone_a, _ = _account(client, "onb2@example.com")
    client.post("/v1/me/onboarding/complete", headers=phone_a)
    tokens = login(client, "onb2@example.com")  # второй телефон — новая сессия
    phone_b = {"Authorization": f"Bearer {tokens['access_token']}"}
    assert client.get("/v1/me", headers=phone_b).json()["onboarding_done"] is True


def test_restart_threshold_is_server_setting(client, monkeypatch):
    assert client.get("/v1/app/config").json()["onboarding_restart_minutes"] == 5
    monkeypatch.setattr(settings, "onboarding_restart_minutes", 10)
    assert client.get("/v1/app/config").json()["onboarding_restart_minutes"] == 10
