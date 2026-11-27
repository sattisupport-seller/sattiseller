"""Исправления по независимой проверке безопасности 27.11.2026 (К-21, часть 2, п.12): H1, M1, M2, M3, L1, L7."""

import time

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app import ratelimit
from app.admin import totp_code
from app.config import settings
from app.db import engine
from app.models import AIUsageEvent, AuthCode, User
from tests.conftest import confirm_age, login
from tests.test_account_deletion import _last_code

ADMIN = "audit-admin@example.com"


def _admin_headers(client, monkeypatch):
    monkeypatch.setattr(settings, "admin_email", ADMIN)
    tokens = login(client, ADMIN)
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    secret = client.post("/v1/admin/2fa/setup", headers=headers).json()["secret"]
    assert client.post("/v1/admin/2fa/enable", headers=headers, json={"code": totp_code(secret)}).status_code == 200
    return headers, secret


def test_h1_admin_totp_attempts_are_limited(client, monkeypatch):
    ratelimit.reset()
    headers, secret = _admin_headers(client, monkeypatch)
    codes = [client.post("/v1/admin/session", headers=headers, json={"code": f"{i:06d}"}).status_code
             for i in range(12)]
    assert 429 in codes and codes.index(429) <= 10  # 10 попыток за 15 минут (вместе с включением 2FA)
    r = client.post("/v1/admin/session", headers=headers, json={"code": totp_code(secret, at=time.time() + 30)})
    assert r.status_code == 429 and r.json()["error"]["code"] == "admin_code_locked"  # даже верный — подождать
    ratelimit.reset()


def _user_with_code(client, email):
    tokens = login(client, email)
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    assert client.post("/v1/me/deletion/start", headers=headers).status_code == 202
    return headers, _last_code(email)


def _wrong(code: str) -> str:
    return "000000" if code != "000000" else "111111"


def test_m2_deletion_code_burns_after_five_wrong_attempts(client):
    ratelimit.reset()
    headers, code = _user_with_code(client, "audit-del@example.com")
    for _ in range(settings.code_max_attempts):
        assert client.post("/v1/me/deletion/confirm", headers=headers, json={"code": _wrong(code)}).status_code == 400
    # верный код после 5 неверных уже не принимается — нужен новый из письма
    assert client.post("/v1/me/deletion/confirm", headers=headers, json={"code": code}).status_code == 400
    with DbSession(engine) as db:
        assert db.scalar(select(User).where(User.email == "audit-del@example.com")) is not None


def test_m2_deactivation_uses_same_attempt_limit(client):
    ratelimit.reset()
    headers, code = _user_with_code(client, "audit-deact@example.com")
    for _ in range(settings.code_max_attempts):
        client.post("/v1/me/deactivation/confirm", headers=headers, json={"code": _wrong(code)})
    assert client.post("/v1/me/deactivation/confirm", headers=headers, json={"code": code}).status_code == 400


def test_m2_deletion_start_is_limited(client):
    ratelimit.reset()
    tokens = login(client, "audit-start@example.com")
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    codes = [client.post("/v1/me/deletion/start", headers=headers).status_code for _ in range(7)]
    assert codes[:5] == [202] * 5 and codes[5] == 429
    ratelimit.reset()


def test_m1_web_deletion_code_burns_after_five_wrong_attempts(client):
    ratelimit.reset()
    email = "audit-web@example.com"
    login(client, email)
    client.post("/delete-account/start", data={"email": email})
    code = _last_code(email)
    for _ in range(settings.code_max_attempts):
        client.post("/delete-account/confirm", data={"email": email, "code": _wrong(code)})
    r = client.post("/delete-account/confirm", data={"email": email, "code": code})
    assert "Аккаунт удалён" not in r.text
    with DbSession(engine) as db:
        rows = db.scalars(select(AuthCode).where(AuthCode.email == email, AuthCode.purpose == "delete")).all()
        assert rows and rows[-1].used and rows[-1].attempts >= settings.code_max_attempts
    ratelimit.reset()


def test_m3_long_facts_rejected_before_model(client, demo):
    r = client.post("/v1/ai/product-drafts", headers=demo["headers"],
                    data={"shop_id": demo["shop_id"], "facts": "а" * 1001, "languages": "ru"})
    assert r.status_code == 422


def _drafts(shop_id):
    with DbSession(engine) as db:
        return len(db.scalars(select(AIUsageEvent).where(AIUsageEvent.shop_id == shop_id,
                                                         AIUsageEvent.kind == "draft")).all())


def test_m3_quota_reserved_before_model_call(client, demo, monkeypatch):
    """Резерв квоты до вызова модели: во время вызова запись уже есть; после — одна запись, не две."""
    from app import api as api_module
    from app import draft_ai

    monkeypatch.setattr(settings, "ai_live", True)
    monkeypatch.setattr(settings, "anthropic_api_key", "sk-test")
    seen = {}

    def fake_live(facts, photos):
        seen["during"] = _drafts(demo["shop_id"])
        return draft_ai.LiveResult(draft={"titles": ["Кружка"] * 3, "description": "Кружка.",
                                          "characteristics": [{"name": "Объём", "value": "Уточнить"}]},
                                   tin=100, tout=50)

    monkeypatch.setattr(api_module.draft_ai, "live_draft", fake_live)
    before = _drafts(demo["shop_id"])
    r = client.post("/v1/ai/product-drafts", headers=demo["headers"],
                    data={"shop_id": demo["shop_id"], "facts": "Кружка белая", "languages": "ru"})
    assert r.status_code == 201 and r.json()["generatedBy"] == "ai"
    assert seen["during"] == before + 1  # запись появилась до ответа модели
    assert _drafts(demo["shop_id"]) == before + 1  # не задвоено


def test_m3_reservation_released_on_fallback(client, demo, monkeypatch):
    from app import api as api_module
    from app import draft_ai

    monkeypatch.setattr(settings, "ai_live", True)
    monkeypatch.setattr(settings, "anthropic_api_key", "sk-test")

    def broken(facts, photos):
        raise draft_ai.DraftFallback("сбой модели")

    monkeypatch.setattr(api_module.draft_ai, "live_draft", broken)
    before = _drafts(demo["shop_id"])
    r = client.post("/v1/ai/product-drafts", headers=demo["headers"],
                    data={"shop_id": demo["shop_id"], "facts": "Кружка белая", "languages": "ru"})
    assert r.status_code == 201 and r.json()["generatedBy"] == "template"
    assert _drafts(demo["shop_id"]) == before  # шаблон квоту не тратит


def test_l1_store_purchase_removed_with_account(client):
    from app.accounts import delete_user_account
    from app.store_billing import StorePurchase

    tokens = login(client, "audit-buy@example.com")
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    confirm_age(client, headers)
    shop_id = client.post("/v1/shops", headers=headers, json={"name": "М"}).json()["id"]
    with DbSession(engine) as db:
        db.add(StorePurchase(store="apple", purchase_key="orig-audit-1", shop_id=shop_id,
                             product_id="kz.satti.seller.monthly", state="active"))
        db.commit()
        delete_user_account(db, db.scalar(select(User).where(User.email == "audit-buy@example.com")))
    with DbSession(engine) as db:
        assert db.scalar(select(StorePurchase).where(StorePurchase.purchase_key == "orig-audit-1")) is None
