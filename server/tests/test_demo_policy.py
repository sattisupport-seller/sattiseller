"""ADR-0005: демо живёт 24 часа от создания; не больше 3 новых демо и сбросов в сутки с одного устройства."""

from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from app import api as api_module
from app.db import engine
from app.models import Shop
from app.ratelimit import reset as reset_limits


def _session(client, device):
    r = client.post("/v1/demo/session", headers={"X-Device-Id": device})
    assert r.status_code == 200, r.text
    return r.json()


def _later(monkeypatch, hours):
    real = api_module.utcnow()
    monkeypatch.setattr(api_module, "utcnow", lambda: real + timedelta(hours=hours))


def test_demo_expires_after_24_hours_and_old_shop_is_deleted(client, monkeypatch):
    reset_limits()
    first = _session(client, "policy-device-lifetime")
    _later(monkeypatch, 25)
    second = _session(client, "policy-device-lifetime")
    assert second["shop_id"] != first["shop_id"]
    with DbSession(engine) as db:
        assert db.scalar(select(func.count()).select_from(Shop).where(Shop.id == first["shop_id"])) == 0


def test_demo_is_still_alive_at_23_hours(client, monkeypatch):
    reset_limits()
    first = _session(client, "policy-device-alive")
    _later(monkeypatch, 23)
    again = _session(client, "policy-device-alive")
    assert again["shop_id"] == first["shop_id"]


def test_fourth_demo_in_a_day_from_one_device_is_refused(client, monkeypatch):
    reset_limits()
    device = "policy-device-limit"
    _session(client, device)  # 1: создание
    _later(monkeypatch, 25)
    _session(client, device)  # 2: пересоздание после истечения
    _later(monkeypatch, 26)
    _session(client, device)  # 3
    _later(monkeypatch, 27)
    r = client.post("/v1/demo/session", headers={"X-Device-Id": device})
    assert r.status_code == 429
    assert r.json()["error"]["code"] == "rate_limited"


def test_demo_reset_counts_toward_the_device_limit(client):
    reset_limits()
    device = "policy-device-reset"
    s = _session(client, device)
    h = {"Authorization": f"Bearer {s['access_token']}"}
    assert client.post("/v1/demo/reset", headers=h).status_code == 200  # 2
    assert client.post("/v1/demo/reset", headers=h).status_code == 200  # 3
    r = client.post("/v1/demo/reset", headers=h)  # 4
    assert r.status_code == 429


def test_limit_is_per_device(client):
    reset_limits()
    for _ in range(3):
        _session(client, "policy-device-a")
    assert client.post("/v1/demo/session", headers={"X-Device-Id": "policy-device-a"}).status_code == 200
    _session(client, "policy-device-b")  # другое устройство — свой лимит
