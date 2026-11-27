"""К-24 (решение владельца 27.11.2026): отдельного согласия на ИИ нет — оно входит в галочку условий при регистрации.
ИИ работает сразу после регистрации; при новой версии условий обновлённое согласие показывается один раз (1.19)."""

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.config import settings
from app.db import engine
from app.models import User
from tests.conftest import confirm_age, login

ASK = {"question": "Когда доставка?", "tone": "polite"}


def _registered(client, email):
    tokens = login(client, email)
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    confirm_age(client, headers)
    shop_id = client.post("/v1/shops", headers=headers, json={"name": "Магазин"}).json()["id"]
    return headers, shop_id


def test_ai_works_right_after_registration_without_extra_consent(client, monkeypatch):
    monkeypatch.setattr(settings, "billing_enforced", False)
    headers, shop_id = _registered(client, "k24-ai@example.com")
    assert client.get(f"/v1/ai/quota?shop_id={shop_id}", headers=headers).json()["consent_active"] is True
    r = client.post("/v1/ai/reply-drafts", params={"shop_id": shop_id}, headers=headers, json=ASK)
    assert r.status_code == 201, r.text


def test_demo_ai_works_without_consent_screen(client, demo):
    q = client.get(f"/v1/ai/quota?shop_id={demo['shop_id']}", headers=demo["headers"]).json()
    assert q["consent_active"] is True


def test_without_checkbox_ai_is_closed(client):
    """Без галочки при входе (условия с согласием на ИИ не приняты) ИИ не работает."""
    tokens = login(client, "k24-nocheck@example.com", accept_terms=False)
    assert tokens["terms_consent_required"] is True
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    assert client.get("/v1/me", headers=headers).json()["terms_consent_required"] is True


def test_old_terms_version_asks_updated_consent_once(client, monkeypatch):
    monkeypatch.setattr(settings, "billing_enforced", False)
    headers, shop_id = _registered(client, "k24-old@example.com")
    with DbSession(engine) as db:  # пользователь соглашался на прежнюю версию (без строки об ИИ)
        db.scalar(select(User).where(User.email == "k24-old@example.com")).terms_version = "2026-11-22-1"
        db.commit()
    assert client.get("/v1/me", headers=headers).json()["terms_consent_required"] is True
    r = client.post("/v1/ai/reply-drafts", params={"shop_id": shop_id}, headers=headers, json=ASK)
    assert r.status_code == 403 and r.json()["error"]["code"] == "terms_consent_required"
    assert client.post("/v1/me/terms", headers=headers, json={"accepted": True}).status_code == 200
    assert client.get("/v1/me", headers=headers).json()["terms_consent_required"] is False
    r = client.post("/v1/ai/reply-drafts", params={"shop_id": shop_id}, headers=headers, json=ASK)
    assert r.status_code == 201


def test_legal_version_raised_for_ai_line():
    assert settings.legal_version == "2026-11-27-1"
