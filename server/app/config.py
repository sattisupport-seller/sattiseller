"""Настройки сервера и служебная конфигурация для приложения (GET /v1/app/config)."""

import os
from pathlib import Path

from pydantic import BaseModel

BASE_DIR = Path(__file__).resolve().parent.parent
def production_config_problems() -> list[str]:
    """Что нельзя оставлять по умолчанию при SATTI_ENV=production (QA, риск R5). Пустой список — всё в порядке."""
    if os.environ.get("SATTI_ENV", "").lower() != "production":
        return []
    problems: list[str] = []
    if settings.billing_pepper == "dev-only-change-me":
        problems.append("SATTI_BILLING_PEPPER не задан: используется значение разработки")
    if settings.admin_totp_key == "dev-only-change-me":
        problems.append("SATTI_TOTP_KEY не задан: секрет 2FA администратора шифруется ключом разработки")
    if not settings.smtp_host:
        problems.append("SATTI_SMTP_HOST не задан: письма с кодами пишутся в папку outbox и не доходят до людей")
    if settings.kaspi_connection_enabled and not settings.kaspi_key:
        problems.append("KASPI_ENABLED=1, но SATTI_KASPI_KEY не задан: токены Kaspi нечем шифровать")
    if any("localhost" in o or "127.0.0.1" in o for o in os.environ.get(
            "SATTI_CORS_ORIGINS", "http://localhost:8081,http://127.0.0.1:8081").split(",")):
        problems.append("SATTI_CORS_ORIGINS содержит localhost")
    if not settings.public_base_url.startswith("https://"):
        problems.append("SATTI_PUBLIC_BASE_URL должен быть https:// (адреса политики и условий для магазинов)")
    if settings.email_login_enabled:
        problems.append("SATTI_EMAIL_LOGIN=1 в продакшене: вход по коду должен быть выключен")
    # AUD-10: критичные флаги не должны молча оставаться в состоянии разработки
    if settings.billing_test_mode:
        problems.append("SATTI_BILLING_TEST_MODE=1 в продакшене: пробный период выдаётся без магазина приложений")
    if not settings.billing_enforced and not settings.free_access:
        problems.append("блокировка по подписке выключена: задайте SATTI_BILLING_ENFORCED=1 "
                        "или SATTI_FREE_ACCESS=1 для бесплатной беты")
    if os.environ.get("SATTI_SCHEDULER", "0") != "1":
        problems.append("SATTI_SCHEDULER не включён: удаление данных по хранению (90 дней) не запустится")
    if not settings.google_client_ids and not os.environ.get("SATTI_APPLE_CLIENT_ID") and not settings.email_login_enabled:
        problems.append("не задан ни один способ входа: SATTI_GOOGLE_CLIENT_IDS или SATTI_APPLE_CLIENT_ID")
    return problems


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
    ai_daily_limit: int = 30  # ТЗ 2.1, раздел 11.2: вопросы и черновики вместе (ADR-0005)
    # Бюджет ИИ на весь сервис (ТЗ 2.1, 11.2): месячный, дневной — 1/20 месячного; стоимость одного вызова
    ai_budget_monthly_usd: float = float(os.environ.get("SATTI_AI_BUDGET_MONTHLY_USD", "20"))
    # дневной лимит ИИ (ТЗ 2.1, 11.2): по умолчанию — 1/20 месячного; в тестах можно задать явно
    ai_budget_daily_usd: float | None = (float(os.environ["SATTI_AI_BUDGET_DAILY_USD"])
                                         if os.environ.get("SATTI_AI_BUDGET_DAILY_USD") else None)
    ai_cost_per_call_micro_usd: int = int(float(os.environ.get("SATTI_AI_COST_PER_CALL_USD", "0")) * 1_000_000)
    ai_max_question_length: int = 500
    import_max_bytes: int = 5 * 1024 * 1024
    import_max_rows: int = 5000
    import_max_unzipped_bytes: int = 50 * 1024 * 1024
    demo_idle_days: int = 30  # устарело: демо живёт 24 часа (ADR-0005), см. demo_lifetime_hours
    demo_lifetime_hours: int = 24  # ADR-0005: демо-песочница живёт 24 часа от создания
    demo_per_device_per_day: int = 3  # ADR-0005: не больше 3 новых демо в сутки с одного устройства (и сбросов)
    ai_consent_version: str = "2026-11-19"
    ai_service_name: str = "Satti AI (тестовый провайдер)"
    # 2.6: подключение Kaspi выключено по умолчанию; письменного разрешения Kaspi ещё нет (spec-2.1, раздел 22)
    # 3.6: почта. Без SATTI_SMTP_HOST письма пишутся в папку outbox (разработка и тесты)
    smtp_host: str = os.environ.get("SATTI_SMTP_HOST", "")
    smtp_port: int = int(os.environ.get("SATTI_SMTP_PORT", "587"))
    smtp_user: str = os.environ.get("SATTI_SMTP_USER", "")
    smtp_password: str = os.environ.get("SATTI_SMTP_PASSWORD", "")
    smtp_from: str = os.environ.get("SATTI_SMTP_FROM", "Satti Seller <no-reply@example.invalid>")
    smtp_starttls: bool = os.environ.get("SATTI_SMTP_STARTTLS", "1") == "1"
    smtp_timeout: float = float(os.environ.get("SATTI_SMTP_TIMEOUT", "20"))
    # 1.4: адрес владельца для оповещений о бюджете ИИ (80% и 100%)
    owner_alert_email: str = os.environ.get("SATTI_OWNER_ALERT_EMAIL", "").strip().lower()
    kaspi_connection_enabled: bool = os.environ.get("KASPI_ENABLED", "0") == "1"
    # 2.4: ключ шифрования токенов Kaspi (Fernet, 32 байта в base64). В продакшене обязателен.
    kaspi_key: str = os.environ.get("SATTI_KASPI_KEY", "")
    # QA-15: публичный адрес сайта (политика и условия по путям /privacy и /terms)
    public_base_url: str = os.environ.get("SATTI_PUBLIC_BASE_URL", "").rstrip("/")
    # 1.19: версия условий и политики; при смене — повторное согласие всех пользователей
    legal_version: str = os.environ.get("SATTI_LEGAL_VERSION", "2026-11-20-1")
    # Подписка (ТЗ 2.1, раздел 8–9). В разработке и до подключения магазинов приложения выключено.
    billing_enforced: bool = os.environ.get("SATTI_BILLING_ENFORCED", "0") == "1"
    # AUD-10: бесплатная бета осознанно, а не по умолчанию (блокировка выключена, пока нет оплаты)
    free_access: bool = os.environ.get("SATTI_FREE_ACCESS", "0") == "1"
    billing_test_mode: bool = os.environ.get("SATTI_BILLING_TEST_MODE", "0") == "1"
    billing_pepper: str = os.environ.get("SATTI_BILLING_PEPPER", "dev-only-change-me")
    # Ключ шифрования секрета 2FA администратора в базе (O2, QA). В продакшене обязателен.
    admin_totp_key: str = os.environ.get("SATTI_TOTP_KEY", "dev-only-change-me")
    subscription_price_text: str = "9 900 ₸ в месяц"
    # Администратор: только владелец (spec-2.1, 14.1). Пустое значение — панель закрыта.
    admin_email: str = os.environ.get("SATTI_ADMIN_EMAIL", "").strip().lower()
    # Вход: Apple и Google (ТЗ 2.1, раздел 5). Идентификаторы приложения у провайдеров — после аккаунтов владельца.
    apple_client_id: str = os.environ.get("SATTI_APPLE_CLIENT_ID", "kz.satti.seller")
    google_client_ids: str = os.environ.get("SATTI_GOOGLE_CLIENT_IDS", "")
    # Вход по email-коду — только для разработки и тестов (ADR-0004). В продакшене выключен.
    email_login_enabled: bool = os.environ.get("SATTI_EMAIL_LOGIN", "0") == "1"
    # AUD-05: защита демо-режима — новые демо-установки с одного адреса и общий предел
    demo_new_per_ip_per_hour: int = int(os.environ.get("SATTI_DEMO_NEW_PER_IP_PER_HOUR", "20"))
    demo_max_installations: int = int(os.environ.get("SATTI_DEMO_MAX", "5000"))


settings = Settings()


class FeatureFlags(BaseModel):
    kaspi_connection: bool = False
    ai_assistant: bool = True
    subscription: bool = False


class AppConfig(BaseModel):
    legal_version: str = ""  # 1.19: версия условий и политики
    min_supported_version_ios: str = "1.0.0"
    min_supported_version_android: str = "1.0.0"
    maintenance_message: str | None = None
    ai_service_name: str = settings.ai_service_name
    # QA-15: адреса политики и условий — из одной переменной SATTI_PUBLIC_BASE_URL (без неё — заглушка для разработки)
    privacy_url: str = f"{settings.public_base_url}/privacy" if settings.public_base_url else "https://example.invalid/privacy"
    terms_url: str = f"{settings.public_base_url}/terms" if settings.public_base_url else "https://example.invalid/terms"
    flags: FeatureFlags = FeatureFlags(kaspi_connection=settings.kaspi_connection_enabled)


def get_app_config() -> AppConfig:
    cfg = AppConfig()
    cfg.legal_version = settings.legal_version
    # адреса берутся на момент запроса: переменная может измениться без перезапуска модуля (QA-15)
    if settings.public_base_url:
        cfg.privacy_url = f"{settings.public_base_url}/privacy"
        cfg.terms_url = f"{settings.public_base_url}/terms"
    return cfg
