"""AUD-12: отчёты из кэша; запись в магазин сбрасывает кэш; TTL не даёт устареть."""

from app import api as api_module
from app import reportcache


def _counting(monkeypatch, name: str) -> dict:
    calls = {"n": 0}
    real = getattr(api_module, name)

    def wrapper(*args, **kwargs):
        calls["n"] += 1
        return real(*args, **kwargs)

    monkeypatch.setattr(api_module, name, wrapper)
    return calls


def test_report_is_cached_until_shop_changes(client, demo, monkeypatch):
    reportcache.clear()
    calls = _counting(monkeypatch, "overview")
    url = f"/v1/shops/{demo['shop_id']}/overview?period=7d"

    first = client.get(url, headers=demo["headers"]).json()
    second = client.get(url, headers=demo["headers"]).json()
    assert first == second
    assert calls["n"] == 1  # второй ответ — из кэша

    # запись, которая меняет данные магазина (демо-сброс): кэш сбрасывается, отчёт считается заново
    r = client.post("/v1/demo/reset", headers=demo["headers"])
    assert r.status_code == 200
    client.get(url, headers=demo["headers"])
    assert calls["n"] == 2


def test_zero_ttl_disables_reuse(client, demo, monkeypatch):
    reportcache.clear()
    calls = _counting(monkeypatch, "profit_breakdown")
    monkeypatch.setattr(reportcache, "TTL_SECONDS", 0.0)
    url = f"/v1/shops/{demo['shop_id']}/profit-breakdown?period=7d"
    client.get(url, headers=demo["headers"])
    client.get(url, headers=demo["headers"])
    assert calls["n"] == 2


def test_cache_is_per_shop(client, demo, monkeypatch):
    reportcache.clear()
    calls = _counting(monkeypatch, "overview")
    other = client.post("/v1/demo/session", headers={"X-Device-Id": "cache-other-device-0001"}).json()
    other_headers = {"Authorization": f"Bearer {other['access_token']}"}
    client.get(f"/v1/shops/{demo['shop_id']}/overview?period=7d", headers=demo["headers"])
    assert calls["n"] == 1
    # первый запрос к другому магазину не должен брать ответ первого
    client.get(f"/v1/shops/{other['shop_id']}/overview?period=7d", headers=other_headers)
    assert calls["n"] == 2
