"""AUD-05: демо-режим нельзя создать без ограничений — лимит на новые установки с адреса и общий предел."""

from app.config import settings


def _new_device(client, i: int):
    return client.post("/v1/demo/session", headers={"X-Device-Id": f"audit-device-{i:04d}"})


def test_new_demo_installations_limited_per_ip(client, monkeypatch):
    monkeypatch.setattr(settings, "demo_new_per_ip_per_hour", 3)
    codes = [_new_device(client, i).status_code for i in range(5)]
    assert codes == [200, 200, 200, 429, 429]
    assert _new_device(client, 3).json()["error"]["code"] == "rate_limited"


def test_existing_installation_is_not_limited(client, monkeypatch):
    monkeypatch.setattr(settings, "demo_new_per_ip_per_hour", 1)
    assert _new_device(client, 1).status_code == 200
    # та же установка снова — не новое создание, лимит не расходует и не блокируется
    for _ in range(3):
        assert _new_device(client, 1).status_code == 200


def test_global_cap_on_installations(client, monkeypatch):
    monkeypatch.setattr(settings, "demo_max_installations", 2)
    assert _new_device(client, 1).status_code == 200
    assert _new_device(client, 2).status_code == 200
    r = _new_device(client, 3)
    assert r.status_code == 503
    assert r.json()["error"]["code"] == "demo_full"
    # уже созданная установка продолжает работать
    assert _new_device(client, 1).status_code == 200
