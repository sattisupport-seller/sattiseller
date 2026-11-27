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
    monkeypatch.setattr(settings, "smtp_host", "smtp.example.invalid")  # 3.6: письма с кодами идут по SMTP
    monkeypatch.setattr(settings, "owner_name", "Имя оператора")  # юридические тексты
    monkeypatch.setattr(settings, "apple_private_key_path", "/srv/satti/secrets/apple.p8")  # К-21: проверка покупок
    monkeypatch.setattr(settings, "google_service_account_path", "/srv/satti/secrets/google.json")
    monkeypatch.setattr(settings, "google_rtdn_token", "x" * 32)
    monkeypatch.setattr(settings, "device_check_mode", "store")
    return monkeypatch


def test_fake_device_check_refused(good_production):
    good_production.setattr(settings, "device_check_mode", "fake")
    assert any("SATTI_DEVICE_CHECK_MODE" in p for p in production_config_problems())


def test_enforced_billing_needs_store_keys(good_production):
    good_production.setattr(settings, "apple_private_key_path", "")
    good_production.setattr(settings, "google_service_account_path", "")
    assert any("ключи App Store" in p for p in production_config_problems())


def test_short_rtdn_token_refused(good_production):
    good_production.setattr(settings, "google_rtdn_token", "short")
    assert any("SATTI_GOOGLE_RTDN_TOKEN" in p for p in production_config_problems())


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


def test_smtp_host_required(good_production):
    good_production.setattr(settings, "smtp_host", "")
    assert any("SATTI_SMTP_HOST" in p for p in production_config_problems())


def test_owner_name_required(good_production):
    good_production.setattr(settings, "owner_name", "")
    assert any("SATTI_OWNER_NAME" in p for p in production_config_problems())
