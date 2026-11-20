"""AUD-10: в продакшене критичные флаги не остаются в состоянии разработки."""

import pytest

from app.config import production_config_problems, settings


@pytest.fixture
def good_production(monkeypatch):
    """Полностью настроенный продакшен: список проблем пуст. Тесты меняют по одному параметру."""
    monkeypatch.setenv("SATTI_ENV", "production")
    monkeypatch.setenv("SATTI_CORS_ORIGINS", "https://seller.example.invalid")
    monkeypatch.setenv("SATTI_SCHEDULER", "1")
    monkeypatch.setattr(settings, "public_base_url", "https://satti.example.invalid")  # QA-15
    monkeypatch.setenv("SATTI_APPLE_CLIENT_ID", "kz.satti.seller")
    monkeypatch.setattr(settings, "billing_pepper", "настоящий-перец")
    monkeypatch.setattr(settings, "admin_totp_key", "настоящий-ключ")
    monkeypatch.setattr(settings, "email_login_enabled", False)
    monkeypatch.setattr(settings, "billing_test_mode", False)
    monkeypatch.setattr(settings, "billing_enforced", True)
    monkeypatch.setattr(settings, "free_access", False)
    monkeypatch.setattr(settings, "google_client_ids", "")
    return monkeypatch


def test_fully_configured_production_has_no_problems(good_production):
    assert production_config_problems() == []


def test_test_billing_mode_refused(good_production):
    good_production.setattr(settings, "billing_test_mode", True)
    assert any("BILLING_TEST_MODE" in p for p in production_config_problems())


def test_disabled_enforcement_refused_unless_free_access(good_production):
    good_production.setattr(settings, "billing_enforced", False)
    assert any("SATTI_BILLING_ENFORCED" in p for p in production_config_problems())
    good_production.setattr(settings, "free_access", True)
    assert not any("SATTI_BILLING_ENFORCED" in p for p in production_config_problems())


def test_scheduler_required(good_production):
    good_production.setenv("SATTI_SCHEDULER", "0")
    assert any("SATTI_SCHEDULER" in p for p in production_config_problems())


def test_some_login_method_required(good_production):
    good_production.delenv("SATTI_APPLE_CLIENT_ID")
    good_production.setattr(settings, "google_client_ids", "")
    assert any("способ входа" in p for p in production_config_problems())
    good_production.setattr(settings, "google_client_ids", "client-1.apps.googleusercontent.com")
    assert not any("способ входа" in p for p in production_config_problems())
