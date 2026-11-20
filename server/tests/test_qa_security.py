"""QA: безопасность и устойчивость к некорректному вводу (docs/qa/audit-and-plan.md, R1–R9).

Ожидания — из ТЗ и принципов безопасности. Тест, который не проходит, — находка, а не повод менять ожидание.
"""

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from app.config import settings
from app.db import engine
from app.models import Shop
from tests.conftest import confirm_age, login

SQLI = ["' OR '1'='1", "1; DROP TABLE shops; --", "' UNION SELECT id FROM users --", "%' OR 1=1 --", "\x00", "../../etc/passwd"]
XSS = ["<script>alert(1)</script>", "<img src=x onerror=alert(1)>", "\"'><svg/onload=alert(1)>"]


def _owner(client, email):
    tokens = login(client, email)
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    confirm_age(client, headers)
    r = client.post("/v1/shops", headers=headers, json={"name": "Магазин " + email, "timezone": "Asia/Almaty", "language": "ru"})
    assert r.status_code == 201, r.text
    return headers, r.json()["id"]


def _shop_count(db_session_factory=DbSession):
    with db_session_factory(engine) as db:
        return db.scalar(select(func.count()).select_from(Shop))


# ---------- R1: разграничение прав между аккаунтами ----------

def test_other_account_cannot_read_any_shop_endpoint(client):
    a_headers, a_shop = _owner(client, "owner-a@example.com")
    b_headers, _ = _owner(client, "owner-b@example.com")
    paths = [
        f"/v1/shops/{a_shop}/overview?period=7d",
        f"/v1/shops/{a_shop}/profit-breakdown?period=7d",
        f"/v1/shops/{a_shop}/orders?period=7d",
        f"/v1/shops/{a_shop}/products?period=7d",
        f"/v1/shops/{a_shop}/products/missing-costs",
        f"/v1/shops/{a_shop}/commissions",
        f"/v1/shops/{a_shop}/expenses",
        f"/v1/shops/{a_shop}/tax",
        f"/v1/shops/{a_shop}/subscription",
        f"/v1/shops/{a_shop}/exports/profit.xlsx?period=7d",
        f"/v1/shops/{a_shop}/orders/no-such-order",
        f"/v1/shops/{a_shop}/products/no-such-product",
        f"/v1/ai/quota?shop_id={a_shop}",
    ]
    for path in paths:
        r = client.get(path, headers=b_headers)
        assert r.status_code in (403, 404), f"{path} → {r.status_code}"
        assert "Магазин owner-a" not in r.text, path


def test_other_account_cannot_write_to_foreign_shop(client):
    _, a_shop = _owner(client, "owner-c@example.com")
    b_headers, _ = _owner(client, "owner-d@example.com")
    r1 = client.post(f"/v1/shops/{a_shop}/commissions", headers=b_headers,
                     json={"category": "Чужая", "rate_percent": "5", "effective_from": None})
    r2 = client.post(f"/v1/shops/{a_shop}/tax", headers=b_headers, json={"enabled": True, "rate_percent": "9"})
    r3 = client.post(f"/v1/shops/{a_shop}/expenses", headers=b_headers,
                     json={"kind": "ads", "amount": "100", "period_start": "2026-11-01", "period_end": "2026-11-30"})
    assert r1.status_code in (403, 404) and r2.status_code in (403, 404) and r3.status_code in (403, 404)


def test_demo_shop_is_not_visible_to_account(client, demo):
    _, _ = _owner(client, "owner-e@example.com")
    b = login(client, "owner-e@example.com")
    r = client.get(f"/v1/shops/{demo['shop_id']}/overview", headers={"Authorization": f"Bearer {b['access_token']}"})
    assert r.status_code in (403, 404)


def test_admin_panel_is_hidden_from_regular_users(client, monkeypatch):
    monkeypatch.setattr(settings, "admin_email", "boss-qa@example.com")
    headers, _ = _owner(client, "user-qa@example.com")
    for path in ("/v1/admin/stats", "/v1/admin/users", "/v1/admin/errors", "/v1/admin/flags"):
        assert client.get(path, headers=headers).status_code == 404, path


# ---------- аутентификация ----------

@pytest.mark.parametrize("auth", ["", "Bearer", "Bearer abc", "Basic dXNlcjpwYXNz", "Bearer " + "a" * 500])
def test_invalid_authorization_is_rejected(client, auth):
    headers = {"Authorization": auth} if auth else {}
    r = client.get("/v1/me", headers=headers)
    assert r.status_code == 401


def test_access_token_stops_working_after_logout(client):
    tokens = login(client, "logout-qa@example.com")
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    assert client.get("/v1/me", headers=headers).status_code == 200
    client.post("/v1/auth/logout", headers=headers, json={"refresh_token": tokens["refresh_token"]})
    assert client.get("/v1/me", headers=headers).status_code == 401


# ---------- R2: некорректный ввод в параметрах ----------

@pytest.mark.parametrize("payload", SQLI)
def test_query_parameters_do_not_crash_or_leak(client, payload):
    from urllib.parse import quote

    payload = quote(payload, safe='')  # браузер кодирует параметры так же
    headers, shop = _owner(client, "fuzz-qa@example.com")
    before = _shop_count()
    urls = [
        f"/v1/shops/{shop}/overview?period={payload}",
        f"/v1/shops/{shop}/orders?period=7d&status={payload}&q={payload}&cursor={payload}",
        f"/v1/shops/{shop}/products?period=7d&sort={payload}&filter={payload}&q={payload}",
        f"/v1/shops/{shop}/products?period=7d&cursor={payload}",
    ]
    for url in urls:
        r = client.get(url, headers=headers)
        assert r.status_code < 500, f"{url} → {r.status_code}"
        assert "Traceback" not in r.text
    assert _shop_count() == before


# ---------- R3: XSS — данные хранятся и отдаются как текст ----------

@pytest.mark.parametrize("payload", XSS)
def test_xss_payload_is_stored_and_returned_as_json_text(client, payload):
    headers = {"Authorization": f"Bearer {login(client, 'xss-qa@example.com')['access_token']}"}
    confirm_age(client, headers)
    r = client.post("/v1/shops", headers=headers, json={"name": payload, "timezone": "Asia/Almaty", "language": "ru"})
    assert r.status_code == 201
    assert r.headers["content-type"].startswith("application/json")
    listed = client.get("/v1/shops", headers=headers)
    assert listed.headers["content-type"].startswith("application/json")
    assert any(s["name"] == payload for s in listed.json()["items"])


# ---------- R4: заголовки защиты ----------

def test_security_headers_are_present(client):
    r = client.get("/v1/app/config")
    assert r.headers.get("x-content-type-options", "").lower() == "nosniff"
    assert r.headers.get("x-frame-options", "").upper() in ("DENY", "SAMEORIGIN")
    assert "content-security-policy" in {k.lower() for k in r.headers}


def test_html_pages_send_security_headers(client):
    for path in ("/admin", "/privacy", "/terms", "/delete-account"):
        r = client.get(path)
        assert r.headers.get("x-content-type-options", "").lower() == "nosniff", path
        assert r.headers.get("x-frame-options", "").upper() in ("DENY", "SAMEORIGIN"), path


# ---------- R9: ошибки без утечек ----------

def test_bad_json_gives_validation_error_without_traceback(client):
    headers = {"Authorization": f"Bearer {login(client, 'json-qa@example.com')['access_token']}", "Content-Type": "application/json"}
    r = client.post("/v1/shops", headers=headers, content="{not json")
    assert r.status_code == 422
    assert "Traceback" not in r.text and "File \"" not in r.text


def test_long_and_empty_inputs_are_rejected(client):
    headers, shop = _owner(client, "long-qa@example.com")
    assert client.post("/v1/shops", headers=headers, json={"name": "", "timezone": "Asia/Almaty"}).status_code == 422
    assert client.post("/v1/shops", headers=headers, json={"name": "я" * 121, "timezone": "Asia/Almaty"}).status_code == 422
    assert client.post("/v1/shops", headers=headers, json={"name": "ok", "timezone": "Mars/Olympus"}).status_code == 422
    assert client.post("/v1/shops", headers=headers, json={"name": "ok", "timezone": "Asia/Almaty", "language": "en"}).status_code == 422


# ---------- R8: лимиты ----------

def test_email_code_requests_are_limited(client):
    codes = [client.post("/v1/auth/email/start", json={"email": "limit-qa@example.com"}).status_code for _ in range(7)]
    assert codes[:5] == [202] * 5
    assert codes[5] == 429


def test_wrong_codes_lock_after_max_attempts(client):
    login(client, "brute-qa@example.com")  # чтобы код существовал; новый вход создаёт новый код
    client.post("/v1/auth/email/start", json={"email": "brute-qa@example.com"})
    statuses = [client.post("/v1/auth/email/verify", json={"email": "brute-qa@example.com", "code": "000000"}).status_code
                for _ in range(settings.code_max_attempts + 2)]
    assert statuses[-1] == 429 or statuses[-1] == 400
    assert 429 in statuses


# ---------- конфигурация (R5) ----------

def test_no_default_secrets_in_production_mode(monkeypatch):
    """В продакшене (SATTI_ENV=production) нельзя запускать с паролем-заглушкой для хешей подписки."""
    from app import config as cfg

    monkeypatch.setenv("SATTI_ENV", "production")
    monkeypatch.setattr(cfg.settings, "billing_pepper", "dev-only-change-me")
    assert getattr(cfg, "production_config_problems", lambda: [])() != []
