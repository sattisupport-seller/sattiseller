"""Версия согласия на ИИ (К-15, 22.11): согласие действует только для текущей версии текста."""

from app.config import settings


def _quota(client, demo):
    return client.get(f"/v1/ai/quota?shop_id={demo['shop_id']}", headers=demo["headers"]).json()


def test_consent_for_old_version_is_not_active(client, demo, monkeypatch):
    client.post("/v1/ai/consent", headers=demo["headers"], json={"granted": True})
    assert _quota(client, demo)["consent_active"] is True
    monkeypatch.setattr(settings, "ai_consent_version", "2099-01-01-1")  # новая версия текста
    q = _quota(client, demo)
    assert q["consent_active"] is False  # прежнее согласие больше не действует
    assert q["consent_version"] != "2099-01-01-1"


def test_new_consent_on_new_version_restores_access(client, demo, monkeypatch):
    client.post("/v1/ai/consent", headers=demo["headers"], json={"granted": True})
    monkeypatch.setattr(settings, "ai_consent_version", "2099-01-01-1")
    r = client.post("/v1/ai/consent", headers=demo["headers"], json={"granted": True})
    assert r.json()["consent_active"] is True and r.json()["consent_version"] == "2099-01-01-1"


def test_current_version_is_the_photo_text_version():
    assert settings.ai_consent_version == "2026-11-22-2"


def test_drafts_require_new_consent_after_version_change(client, demo, monkeypatch):
    client.post("/v1/ai/consent", headers=demo["headers"], json={"granted": True})
    monkeypatch.setattr(settings, "ai_consent_version", "2099-01-01-1")
    r = client.post("/v1/ai/product-drafts", headers=demo["headers"],
                    data={"shop_id": demo["shop_id"], "facts": "Чашка белая", "languages": "ru"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "ai_consent_required"
