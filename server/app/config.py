"""Настройки сервера и служебная конфигурация для приложения (GET /v1/app/config)."""

import os
from pathlib import Path

from pydantic import BaseModel

BASE_DIR = Path(__file__).resolve().parent.parent


def _load_env_file(path: Path) -> None:
    """Читает server/.env (если файл есть) до чтения настроек. Уже заданные в окружении значения не перезаписываются.
    Пустые значения пропускаются: пустой секрет в шаблоне не должен затирать значение по умолчанию."""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.split(" #", 1)[0].strip()  # комментарий в конце строки отбрасывается
        if key and value and key not in os.environ:
            os.environ[key] = value


_load_env_file(BASE_DIR / ".env")
def production_config_problems() -> list[str]:
    """Что нельзя оставлять по умолчанию при SATTI_ENV=production (QA, риск R5). Пустой список — всё в порядке."""
    if os.environ.get("SATTI_ENV", "").lower() != "production":
        return []
    problems: list[str] = []
    if settings.billing_pepper == "dev-only-change-me":
        problems.append("SATTI_BILLING_PEPPER не задан: используется значение разработки")
    if settings.admin_totp_key == "dev-only-change-me":
        problems.append("SATTI_TOTP_KEY не задан: секрет 2FA администратора шифруется ключом разработки")
    if not settings.owner_name:
        problems.append("SATTI_OWNER_NAME не задан: в юридических текстах будет общий оператор без имени")
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
    # 4.4 (К-21): покупки и пробный период
    if settings.device_check_mode == "fake":
        problems.append("SATTI_DEVICE_CHECK_MODE=fake в продакшене: токен телефона не проверяется у Apple и Google")
    if settings.billing_enforced and not (settings.apple_private_key_path or settings.google_service_account_path):
        problems.append("SATTI_BILLING_ENFORCED=1, но ключи App Store / Google Play не заданы: покупки не проверить")
    if settings.google_service_account_path and len(settings.google_rtdn_token) < 24:
        problems.append("SATTI_GOOGLE_RTDN_TOKEN пустой или короче 24 знаков: адрес уведомлений Google легко подобрать")
    if os.environ.get("SATTI_SCHEDULER", "0") != "1":
        problems.append("SATTI_SCHEDULER не включён: удаление данных по хранению (90 дней) не запустится")
    # 4.4 (К-21): переменные, добавленные после 4.4 — ИИ и карточка с фото, контакты, админка, оповещения
    if settings.ai_live and not settings.anthropic_api_key:
        problems.append("SATTI_AI_LIVE=1, но ANTHROPIC_API_KEY не задан: помощник и карточки будут только шаблоном")
    if settings.ai_live and settings.ai_budget_monthly_usd <= 0:
        problems.append("SATTI_AI_BUDGET_MONTHLY_USD не больше 0: бюджет ИИ не ограничивает расходы")
    if not settings.support_email or settings.support_email.endswith(".invalid"):
        problems.append("SATTI_SUPPORT_EMAIL не задан: блокировка, токен Kaspi и удаление ведут продавца в поддержку")
    if not settings.owner_alert_email:
        problems.append("SATTI_OWNER_ALERT_EMAIL не задан: оповещения владельцу (копии, ошибки, место на диске) не уйдут")
    if not settings.admin_email:
        problems.append("SATTI_ADMIN_EMAIL не задан: админка (блокировка, окно токена, особые условия) недоступна")
    if settings.ip_requests_per_minute <= 0:
        problems.append("SATTI_IP_REQUESTS_PER_MINUTE = 0: лимит запросов с одного адреса на входе выключен")
    if settings.push_mode != "expo":
        problems.append("SATTI_PUSH_MODE не expo: уведомления пишутся в папку outbox/push и не доходят до телефонов")
    # 3.3: вход Apple без ключа Sign in with Apple — при удалении аккаунта токен не отозвать (требование Apple)
    if os.environ.get("SATTI_APPLE_CLIENT_ID") and not (settings.apple_siwa_key_id and settings.apple_siwa_key_path
                                                        and settings.apple_team_id):
        problems.append("вход Apple включён, но SATTI_APPLE_SIWA_KEY_ID / SATTI_APPLE_SIWA_KEY_PATH / SATTI_APPLE_TEAM_ID "
                        "не заданы: при удалении аккаунта токен Apple не будет отозван")
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
    # 3.5: живая модель. Включается только при SATTI_AI_LIVE=1 и заданном ANTHROPIC_API_KEY; иначе — мок.
    ai_live: bool = os.environ.get("SATTI_AI_LIVE", "0") == "1"
    anthropic_api_key: str = os.environ.get("ANTHROPIC_API_KEY", "")
    ai_model: str = os.environ.get("SATTI_AI_MODEL", "claude-haiku-5-5")
    # цены за миллион токенов для учёта бюджета (проверить по актуальному прайсу провайдера)
    # Claude Haiku 5.5: 0,10 $ за миллион входных токенов (документация); другие модели — через переменную окружения
    ai_price_in_per_mtok: float = float(os.environ.get("SATTI_AI_PRICE_IN_PER_MTOK", "0.10"))
    # Claude Haiku 5.5: 0,50 $ за миллион выходных токенов
    ai_price_out_per_mtok: float = float(os.environ.get("SATTI_AI_PRICE_OUT_PER_MTOK", "0.50"))
    ai_cost_per_call_micro_usd: int = int(float(os.environ.get("SATTI_AI_COST_PER_CALL_USD", "0")) * 1_000_000)
    ai_max_question_length: int = 500
    import_max_bytes: int = 5 * 1024 * 1024
    import_max_rows: int = 5000
    import_max_unzipped_bytes: int = 50 * 1024 * 1024
    demo_idle_days: int = 30  # устарело: демо живёт 24 часа (ADR-0005), см. demo_lifetime_hours
    demo_lifetime_hours: int = 24  # ADR-0005: демо-песочница живёт 24 часа от создания
    demo_per_device_per_day: int = 3  # ADR-0005: не больше 3 новых демо в сутки с одного устройства (и сбросов)
    ai_consent_version: str = "2026-11-22-2"  # К-15: текст согласия с фото; прежние согласия не действуют
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
    analytics_enabled: bool = os.environ.get("ANALYTICS_ENABLED", "0") == "1"  # 3.9: за флагом, по умолчанию выключено
    # адрес поддержки (страница /support, тексты магазинов и бета-материалов; пункт 5.8)
    support_email: str = os.environ.get("SATTI_SUPPORT_EMAIL", "").strip()
    # имя оператора для юридических текстов (подставляется вместо {OWNER_NAME}); до регистрации ИП — из переменной
    owner_name: str = os.environ.get("SATTI_OWNER_NAME", "").strip()
    kaspi_connection_enabled: bool = os.environ.get("KASPI_ENABLED", "0") == "1"
    # 2.4: ключ шифрования токенов Kaspi (Fernet, 32 байта в base64). В продакшене обязателен.
    kaspi_key: str = os.environ.get("SATTI_KASPI_KEY", "")
    # QA-15: публичный адрес сайта (политика и условия по путям /privacy и /terms)
    public_base_url: str = os.environ.get("SATTI_PUBLIC_BASE_URL", "").rstrip("/")
    # 1.19: версия условий и политики; при смене — повторное согласие всех пользователей
    legal_version: str = os.environ.get("SATTI_LEGAL_VERSION", "2026-11-27-1")  # К-24: согласие на ИИ входит в галочку условий; всем принять заново
    # Подписка (ТЗ 2.1, раздел 8–9). В разработке и до подключения магазинов приложения выключено.
    billing_enforced: bool = os.environ.get("SATTI_BILLING_ENFORCED", "0") == "1"
    # AUD-10: бесплатная бета осознанно, а не по умолчанию (блокировка выключена, пока нет оплаты)
    free_access: bool = os.environ.get("SATTI_FREE_ACCESS", "0") == "1"
    billing_test_mode: bool = os.environ.get("SATTI_BILLING_TEST_MODE", "0") == "1"
    billing_pepper: str = os.environ.get("SATTI_BILLING_PEPPER", "dev-only-change-me")
    # Ключ шифрования секрета 2FA администратора в базе (O2, QA). В продакшене обязателен.
    admin_totp_key: str = os.environ.get("SATTI_TOTP_KEY", "dev-only-change-me")
    subscription_price_text: str = "9 900 ₸ в месяц"
    # 3.1–3.2 (К-21): проверка покупок через App Store Server API и Google Play Developer API.
    # Без ключей проверка отвечает store_not_configured; в тестах — записанные ответы (httpx.MockTransport).
    apple_bundle_id: str = os.environ.get("SATTI_APPLE_BUNDLE_ID", "kz.satti.seller")
    apple_issuer_id: str = os.environ.get("SATTI_APPLE_ISSUER_ID", "")
    apple_key_id: str = os.environ.get("SATTI_APPLE_KEY_ID", "")
    apple_private_key_path: str = os.environ.get("SATTI_APPLE_PRIVATE_KEY_PATH", "")  # .p8 в server/data/secrets/
    apple_environment: str = os.environ.get("SATTI_APPLE_ENVIRONMENT", "Sandbox")  # Sandbox | Production
    # Две подписки одной группы: с вводным предложением (пробный период) и без него — для телефона с отметкой
    apple_product_trial: str = os.environ.get("SATTI_APPLE_PRODUCT_TRIAL", "kz.satti.seller.monthly")
    apple_product_plain: str = os.environ.get("SATTI_APPLE_PRODUCT_PLAIN", "kz.satti.seller.monthly.notrial")
    google_package_name: str = os.environ.get("SATTI_GOOGLE_PACKAGE_NAME", "kz.satti.seller")
    google_service_account_path: str = os.environ.get("SATTI_GOOGLE_SERVICE_ACCOUNT_PATH", "")  # JSON-ключ, не в git
    google_subscription_id: str = os.environ.get("SATTI_GOOGLE_SUBSCRIPTION_ID", "satti_monthly")
    google_trial_offer_id: str = os.environ.get("SATTI_GOOGLE_TRIAL_OFFER_ID", "trial14")
    # секрет в адресе push-подписки Pub/Sub (RTDN); уведомление само доступ не даёт — сервер перечитывает покупку
    google_rtdn_token: str = os.environ.get("SATTI_GOOGLE_RTDN_TOKEN", "")
    # Пробный период — один на телефон (решение владельца 23.11): DeviceCheck (iOS) и Play Integrity device recall.
    # Ключ DeviceCheck — отдельный ключ Apple (.p8). fake — только тесты и разработка: токен = метка телефона.
    device_check_mode: str = os.environ.get("SATTI_DEVICE_CHECK_MODE", "off")  # off | fake | store
    apple_team_id: str = os.environ.get("SATTI_APPLE_TEAM_ID", "")
    apple_devicecheck_key_id: str = os.environ.get("SATTI_APPLE_DEVICECHECK_KEY_ID", "")
    apple_devicecheck_key_path: str = os.environ.get("SATTI_APPLE_DEVICECHECK_KEY_PATH", "")
    # Администратор: только владелец (spec-2.1, 14.1). Пустое значение — панель закрыта.
    admin_email: str = os.environ.get("SATTI_ADMIN_EMAIL", "").strip().lower()
    # Вход: Apple и Google (ТЗ 2.1, раздел 5). Идентификаторы приложения у провайдеров — после аккаунтов владельца.
    apple_client_id: str = os.environ.get("SATTI_APPLE_CLIENT_ID", "kz.satti.seller")
    # 3.3: ключ Sign in with Apple — обмен authorizationCode на refresh token и отзыв при удалении аккаунта
    # 3.4: пуши — mock (файлы в outbox/push) или expo (Expo Push API → FCM/APNs по ключам EAS)
    push_mode: str = os.environ.get("SATTI_PUSH_MODE", "mock")
    onboarding_restart_minutes: int = int(os.environ.get("SATTI_ONBOARDING_RESTART_MINUTES", "5"))
    # К-21 ч.2 п.11: запросов в минуту с одного адреса на входе сервера (0 — выключено)
    ip_requests_per_minute: int = int(os.environ.get("SATTI_IP_REQUESTS_PER_MINUTE", "300"))
    expo_access_token: str = os.environ.get("SATTI_EXPO_ACCESS_TOKEN", "")
    apple_siwa_key_id: str = os.environ.get("SATTI_APPLE_SIWA_KEY_ID", "")
    apple_siwa_key_path: str = os.environ.get("SATTI_APPLE_SIWA_KEY_PATH", "")  # .p8 в server/data/secrets/
    google_client_ids: str = os.environ.get("SATTI_GOOGLE_CLIENT_IDS", "")
    # Вход по email-коду — только для разработки и тестов (ADR-0004). В продакшене выключен.
    email_login_enabled: bool = os.environ.get("SATTI_EMAIL_LOGIN", "0") == "1"
    # AUD-05: защита демо-режима — новые демо-установки с одного адреса и общий предел
    demo_new_per_ip_per_hour: int = int(os.environ.get("SATTI_DEMO_NEW_PER_IP_PER_HOUR", "20"))
    demo_max_installations: int = int(os.environ.get("SATTI_DEMO_MAX", "5000"))


settings = Settings()


class FeatureFlags(BaseModel):
    kaspi_connection: bool = False
    ai_assistant: bool = True  # включён по умолчанию (решение владельца 22.11); выключатель в админке главнее
    subscription: bool = False
    analytics: bool = False  # 3.9: отправка событий из приложения (ANALYTICS_ENABLED и флаг в админке)


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
    # К-21 (решение владельца 02:24): свернул или закрыл приложение дольше N минут — обучение начинается заново
    onboarding_restart_minutes: int = 5


def get_app_config() -> AppConfig:
    cfg = AppConfig()
    cfg.legal_version = settings.legal_version
    cfg.onboarding_restart_minutes = settings.onboarding_restart_minutes
    # адреса берутся на момент запроса: переменная может измениться без перезапуска модуля (QA-15)
    if settings.public_base_url:
        cfg.privacy_url = f"{settings.public_base_url}/privacy"
        cfg.terms_url = f"{settings.public_base_url}/terms"
    return cfg
