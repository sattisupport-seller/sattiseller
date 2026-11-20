"""Настройки сервера и служебная конфигурация для приложения (GET /v1/app/config)."""

import os
from pathlib import Path

from pydantic import BaseModel

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("SATTI_DATA_DIR", BASE_DIR / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)  # база SQLite и папка писем создаются здесь


class Settings:
    database_url: str = os.environ.get("DATABASE_URL", f"sqlite:///{(DATA_DIR / 'satti.db').as_posix()}")
    outbox_dir: Path = Path(os.environ.get("SATTI_OUTBOX_DIR", DATA_DIR / "outbox"))
    default_timezone: str = "Asia/Almaty"
    access_ttl_minutes: int = 15
    refresh_ttl_days: int = 30
    code_ttl_minutes: int = 10
    code_max_attempts: int = 5
    code_requests_per_hour: int = 5
    import_requests_per_hour: int = 10
    ai_daily_limit: int = 30  # ТЗ 2.1, раздел 11.2: вопросы и черновики вместе
    ai_max_question_length: int = 500
    import_max_bytes: int = 5 * 1024 * 1024
    import_max_rows: int = 5000
    import_max_unzipped_bytes: int = 50 * 1024 * 1024
    demo_idle_days: int = 30
    ai_consent_version: str = "2026-11-19"
    ai_service_name: str = "Satti AI (тестовый провайдер)"
    kaspi_connection_enabled: bool = False
    # Подписка (ТЗ 2.1, раздел 8–9). В разработке и до подключения магазинов приложения выключено.
    billing_enforced: bool = os.environ.get("SATTI_BILLING_ENFORCED", "0") == "1"
    billing_test_mode: bool = os.environ.get("SATTI_BILLING_TEST_MODE", "0") == "1"
    billing_pepper: str = os.environ.get("SATTI_BILLING_PEPPER", "dev-only-change-me")
    subscription_price_text: str = "9 900 ₸ в месяц"
    # Администратор: только владелец (spec-2.1, 14.1). Пустое значение — панель закрыта.
    admin_email: str = os.environ.get("SATTI_ADMIN_EMAIL", "").strip().lower()


settings = Settings()


class FeatureFlags(BaseModel):
    kaspi_connection: bool = False
    ai_assistant: bool = True
    subscription: bool = False


class AppConfig(BaseModel):
    min_supported_version_ios: str = "1.0.0"
    min_supported_version_android: str = "1.0.0"
    maintenance_message: str | None = None
    ai_service_name: str = settings.ai_service_name
    privacy_url: str = "https://example.invalid/privacy"
    terms_url: str = "https://example.invalid/terms"
    flags: FeatureFlags = FeatureFlags(kaspi_connection=settings.kaspi_connection_enabled)


def get_app_config() -> AppConfig:
    return AppConfig()
