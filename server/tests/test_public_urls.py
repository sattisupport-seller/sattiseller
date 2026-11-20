"""QA-15: адреса политики и условий строятся из одной переменной; в продакшене без https запуск отказывает."""

from app import config
from app.config import production_config_problems, settings


def test_policy_and_terms_follow_the_base_url(monkeypatch):
    monkeypatch.setattr(settings, "public_base_url", "https://satti.example.invalid")
    cfg = config.get_app_config()
    assert cfg.privacy_url == "https://satti.example.invalid/privacy"
    assert cfg.terms_url == "https://satti.example.invalid/terms"


def test_without_base_url_a_development_placeholder_is_used(monkeypatch):
    monkeypatch.setattr(settings, "public_base_url", "")
    assert config.get_app_config().privacy_url.endswith("/privacy")


def test_production_refuses_non_https_base_url(monkeypatch):
    monkeypatch.setenv("SATTI_ENV", "production")
    monkeypatch.setattr(settings, "public_base_url", "http://satti.example.invalid")
    assert any("SATTI_PUBLIC_BASE_URL" in p for p in production_config_problems())
