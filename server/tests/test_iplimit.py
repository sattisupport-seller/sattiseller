"""К-21, часть 2, п.11: лимит запросов с одного адреса на входе сервера, в дополнение к лимитам в приложении."""

from app import iplimit
from app.config import settings


def test_counter_per_ip_and_minute():
    iplimit.reset()
    t = 1_800_000_000.0
    assert all(iplimit.hit("1.1.1.1", 3, t) for _ in range(3))
    assert iplimit.hit("1.1.1.1", 3, t) is False      # четвёртый за минуту — отказ
    assert iplimit.hit("2.2.2.2", 3, t) is True       # другой адрес — свой счётчик
    assert iplimit.hit("1.1.1.1", 3, t + 60) is True  # новая минута
    assert ("1.1.1.1", int(t // 60)) not in iplimit._counts  # старые окна удаляются — память не растёт


def test_middleware_returns_429_and_spares_health_and_kaspi(client, monkeypatch):
    iplimit.reset()
    monkeypatch.setattr(settings, "ip_requests_per_minute", 5)
    codes = [client.get("/v1/app/config").status_code for _ in range(6)]
    assert codes[:5] == [200] * 5 and codes[5] == 429
    r = client.get("/v1/app/config")
    assert r.json()["error"]["code"] == "rate_limited" and r.headers["retry-after"] == "60"
    assert client.get("/v1/health").status_code == 200  # сторож не упирается в лимит
    assert client.get("/v1/kaspi/price/x/y").status_code != 429  # прайс для Kaspi не ограничивается
    iplimit.reset()


def test_disabled_with_zero(client, monkeypatch):
    iplimit.reset()
    monkeypatch.setattr(settings, "ip_requests_per_minute", 0)
    assert all(client.get("/v1/app/config").status_code == 200 for _ in range(20))
