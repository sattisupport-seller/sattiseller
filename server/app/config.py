"""Служебная конфигурация для приложения (GET /v1/app/config)."""

from pydantic import BaseModel


class FeatureFlags(BaseModel):
    kaspi_connection: bool = False
    ai_assistant: bool = True
    subscription: bool = False


class AppConfig(BaseModel):
    min_supported_version_ios: str = "1.0.0"
    min_supported_version_android: str = "1.0.0"
    maintenance_message: str | None = None
    ai_service_name: str = "ИИ-сервис"
    privacy_url: str = "https://example.invalid/privacy"
    terms_url: str = "https://example.invalid/terms"
    flags: FeatureFlags = FeatureFlags()


def get_app_config() -> AppConfig:
    return AppConfig()
