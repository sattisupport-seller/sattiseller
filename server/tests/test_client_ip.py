"""AUD-14: за доверенным прокси лимиты считаются по настоящему клиенту, а подделка заголовков не работает."""

from starlette.requests import Request

from app.ratelimit import client_ip


def _request(peer: str, headers: dict[str, str]) -> Request:
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/",
        "query_string": b"",
        "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
        "client": (peer, 1234),
    }
    return Request(scope)


def test_without_trusted_proxy_headers_are_ignored(monkeypatch):
    monkeypatch.delenv("SATTI_TRUSTED_PROXIES", raising=False)
    r = _request("10.0.0.1", {"X-Forwarded-For": "203.0.113.7"})
    assert client_ip(r) == "10.0.0.1"


def test_behind_trusted_proxy_real_client_is_used(monkeypatch):
    monkeypatch.setenv("SATTI_TRUSTED_PROXIES", "10.0.0.1,10.0.0.2")
    r = _request("10.0.0.1", {"X-Forwarded-For": "198.51.100.9, 203.0.113.7, 10.0.0.2"})
    assert client_ip(r) == "203.0.113.7"


def test_spoofed_forwarded_header_from_untrusted_peer_is_ignored(monkeypatch):
    monkeypatch.setenv("SATTI_TRUSTED_PROXIES", "10.0.0.1")
    r = _request("192.0.2.5", {"X-Forwarded-For": "1.2.3.4"})
    assert client_ip(r) == "192.0.2.5"


def test_real_ip_header_used_when_forwarded_is_missing(monkeypatch):
    monkeypatch.setenv("SATTI_TRUSTED_PROXIES", "10.0.0.1")
    r = _request("10.0.0.1", {"X-Real-IP": "203.0.113.8"})
    assert client_ip(r) == "203.0.113.8"
