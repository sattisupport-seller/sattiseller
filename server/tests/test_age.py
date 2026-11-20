"""Возраст 18+ (ADR-0004): без подтверждения магазин не создаётся."""

from tests.conftest import login


def test_shop_creation_requires_age_confirmation(client):
    tokens = login(client, "young@example.com")
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    me = client.get("/v1/me", headers=headers).json()
    assert me["age_confirmed"] is False

    r = client.post("/v1/shops", headers=headers, json={"name": "Магазин", "timezone": "Asia/Almaty", "language": "ru"})
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "age_required"


def test_confirmation_allows_shop_creation(client):
    tokens = login(client, "adult@example.com")
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    assert client.post("/v1/me/age-confirm", headers=headers).status_code == 200
    assert client.get("/v1/me", headers=headers).json()["age_confirmed"] is True
    r = client.post("/v1/shops", headers=headers, json={"name": "Магазин", "timezone": "Asia/Almaty", "language": "ru"})
    assert r.status_code == 201
