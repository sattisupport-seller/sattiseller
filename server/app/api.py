"""HTTP-маршруты Satti API /v1 (docs/spec.md, раздел 5.2)."""

from __future__ import annotations

import io
from datetime import date, datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, Header, Query, Request, Response, UploadFile
from fastapi.responses import PlainTextResponse
from openpyxl import Workbook
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel, Field
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session as DbSession

from . import ai as ai_service
from .accounts import delete_user_account
from .auth import (
    Principal,
    ai_consent_state,
    current_user,
    get_principal,
    issue_tokens,
    set_ai_consent,
    shop_for,
    utcnow,
)
from .config import AppConfig, get_app_config, settings
from .db import get_session
from .demo_template import copy_template, create_demo_from_template, ensure_template
from .flags import is_enabled, require_ai
from .errors import ApiError
from .imports import (
    FIELDS,
    auto_mapping,
    dump_payload,
    errors_csv,
    load_payload,
    missing_required,
    parse_file,
    validate_rows,
)
from .mailer import send_code_email
from .models import (
    AIConversation,
    AITurn,
    AuthCode,
    CommissionPreset,
    DemoInstallation,
    ExpenseEntry,
    ImportBatch,
    NotificationSettings,
    Order,
    Product,
    ProductCostVersion,
    Session,
    Shop,
    User,
)
from .periods import Period, PeriodError, resolve, today_in
from .billing import get_subscription, start_trial, subscription_view, trial_eligible, wipe_shop_content
from .exports import profit_filename, profit_workbook, user_export_zip
from . import reportcache
from .quotalock import quota_guard
from .ratelimit import allow, client_ip
from .schemas import (
    AIQuotaOut,
    CostVersionsOut,
    ExpensesOut,
    MissingCostsOut,
    OrdersPageOut,
    ProductsPageOut,
    AgeConfirmOut,
    CommissionCreatedOut,
    CommissionsOut,
    MeOut,
    OrderDetailOut,
    OverviewOut,
    ProductDetailOut,
    ProfitBreakdownOut,
    ShopsOut,
    SubscriptionOut,
    TaxOut,
)
from .reports import (
    build_facts,
    load_shop,
    order_detail,
    orders_list,
    overview,
    products_list,
    product_detail,
    profit_breakdown,
    missing_costs as missing_costs_list,
)
from .security import hash_code, hash_device_id, new_code

api = APIRouter()

from . import admin as _admin  # noqa: E402  (админ-панель и поддержка, ТЗ 2.1, раздел 14)

from . import social_auth as _social  # noqa: E402  (вход через Apple и Google)

api.include_router(_social.router)
api.include_router(_admin.router)
api.include_router(_admin.me_router)


def _period(name: str | None, shop: Shop) -> Period:
    try:
        return resolve(name or "7d", shop.timezone)
    except PeriodError as exc:
        raise ApiError(422, "validation", str(exc)) from exc


def _limit(limit: int) -> int:
    return max(1, min(limit, 50))


def _cursor(cursor: str | None) -> int:
    try:
        return max(0, int(cursor or 0))
    except ValueError:
        return 0


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _minute() -> str:
    """Ключ времени для кэша отчётов: минута (AUD-12)."""
    return _now().strftime("%Y-%m-%dT%H:%M")


# ---------- служебное ----------

@api.get("/app/config", response_model=AppConfig, tags=["служебное"])
def app_config(db: DbSession = Depends(get_session)) -> AppConfig:
    cfg = get_app_config()
    # флаги берутся из админки (выключатель ИИ, подписка, Kaspi), а не из констант
    cfg.flags.ai_assistant = is_enabled(db, "ai_assistant")
    cfg.flags.kaspi_connection = is_enabled(db, "kaspi_connection")
    cfg.flags.subscription = is_enabled(db, "subscription")
    return cfg


# ---------- вход ----------

class EmailIn(BaseModel):
    email: str = Field(min_length=5, max_length=255)


class VerifyIn(BaseModel):
    email: str = Field(min_length=5, max_length=255)
    code: str = Field(min_length=6, max_length=6)
    accept_terms: bool = False  # 1.19: галочка на экране входа


class RefreshIn(BaseModel):
    refresh_token: str


def _norm_email(email: str) -> str:
    e = email.strip().lower()
    if "@" not in e or e.startswith("@") or e.endswith("@") or " " in e:
        raise ApiError(422, "validation", "Проверьте адрес почты.")
    return e


@api.post("/auth/email/start", status_code=202, tags=["вход"])
def auth_email_start(body: EmailIn, request: Request, db: DbSession = Depends(get_session)) -> dict:
    if not settings.email_login_enabled:
        raise ApiError(404, "not_found")
    email = _norm_email(body.email)
    ip = client_ip(request)
    if not allow(f"code:{email}", settings.code_requests_per_hour) or not allow(f"codeip:{ip}", 20):
        raise ApiError(429, "rate_limited", "Слишком много попыток, подождите 10 минут.")
    code = new_code()
    db.add(AuthCode(email=email, purpose="login", code_hash=hash_code(email, code),
                    expires_at=utcnow() + timedelta(minutes=settings.code_ttl_minutes)))
    db.commit()
    send_code_email(email, code, "login")
    return {"status": "sent", "expires_in": settings.code_ttl_minutes * 60}


@api.post("/auth/email/verify", tags=["вход"])
def auth_email_verify(body: VerifyIn, db: DbSession = Depends(get_session)) -> dict:
    if not settings.email_login_enabled:
        raise ApiError(404, "not_found")
    email = _norm_email(body.email)
    code_row = db.scalar(select(AuthCode).where(AuthCode.email == email, AuthCode.purpose == "login",
                                                AuthCode.used.is_(False)).order_by(AuthCode.expires_at.desc()))
    if code_row is None:
        raise ApiError(400, "code_invalid")
    from .auth import aware

    if aware(code_row.expires_at) < utcnow():
        raise ApiError(400, "code_expired")
    if code_row.attempts >= settings.code_max_attempts:
        raise ApiError(429, "rate_limited", "Слишком много неверных попыток. Запросите новый код.")
    if hash_code(email, body.code) != code_row.code_hash:
        code_row.attempts += 1
        db.commit()
        raise ApiError(400, "code_invalid")
    code_row.used = True
    user = db.scalar(select(User).where(User.email == email))
    created = False
    if user is None:
        user = User(email=email)
        db.add(user)
        db.flush()
        created = True
    tokens = issue_tokens(db, user_id=user.id)
    db.commit()
    if body.accept_terms:
        _record_terms(user)
    db.commit()
    return {**tokens, "user": {"id": user.id, "email": user.email}, "terms_consent_required": user.terms_version != settings.legal_version, "needs_shop_setup": created or
            db.scalar(select(Shop.id).where(Shop.owner_user_id == user.id).limit(1)) is None}


@api.post("/auth/refresh", tags=["вход"])
def auth_refresh(body: RefreshIn, db: DbSession = Depends(get_session)) -> dict:
    from .auth import aware
    from .security import hash_token

    sess = db.scalar(select(Session).where(Session.refresh_hash == hash_token(body.refresh_token)))
    if sess is None or sess.revoked or aware(sess.refresh_expires_at) < utcnow():
        raise ApiError(401, "unauthorized")
    sess.revoked = True  # ротация: старый токен обновления больше не работает
    tokens = issue_tokens(db, user_id=sess.user_id, demo_shop_id=sess.demo_shop_id)
    db.commit()
    return tokens


@api.post("/auth/logout", status_code=204, tags=["вход"])
def auth_logout(principal: Principal = Depends(get_principal), db: DbSession = Depends(get_session)) -> Response:
    sess = db.get(Session, principal.session_id)
    if sess:
        sess.revoked = True
    db.commit()
    return Response(status_code=204)


# ---------- демо ----------

@api.post("/demo/session", tags=["демо"])
def demo_session(request: Request, x_device_id: str = Header(..., alias="X-Device-Id"),
                 db: DbSession = Depends(get_session)) -> dict:
    if not (8 <= len(x_device_id) <= 128):
        raise ApiError(422, "validation")
    ensure_template(db)  # 1.16: шаблон создаётся до других записей запроса (он коммитит транзакцию)
    _purge_idle_demos(db)
    install_id = hash_device_id(x_device_id)
    inst = db.get(DemoInstallation, install_id)
    # Лимиты (allow) открывают своё соединение. Если запрос держит своё, при наплыве пул исчерпывается
    # и запросы ждут друг друга до таймаута (нагрузка 1.16: 41 из 50 отказов). Поэтому перед каждым лимитом — commit.
    db.commit()
    if inst is None:
        # AUD-05: новая демо-установка создаёт магазин с данными — ограничиваем такие создания
        if not allow(f"demo:{client_ip(request)}", settings.demo_new_per_ip_per_hour):
            raise ApiError(429, "rate_limited", "Слишком много новых демо-сессий с этого адреса. Попробуйте позже.")
        total = db.scalar(select(func.count()).select_from(DemoInstallation)) or 0
        db.commit()
        if total >= settings.demo_max_installations:
            raise ApiError(503, "demo_full", "Демо-режим временно недоступен. Попробуйте позже.")
        _check_device_demo_limit(install_id)
        shop = create_demo_from_template(db, today_in(settings.default_timezone))
        inst = DemoInstallation(id=install_id, shop_id=shop.id, created_at=utcnow())
        db.add(inst)
    else:
        inst.last_active_at = utcnow()
        shop_missing = db.get(Shop, inst.shop_id) is None
        db.commit()
        if shop_missing:
            _check_device_demo_limit(install_id)
            shop = create_demo_from_template(db, today_in(settings.default_timezone))
            inst.shop_id = shop.id
            inst.created_at = utcnow()
    db.flush()
    tokens = issue_tokens(db, demo_shop_id=inst.shop_id)
    db.commit()
    return {**tokens, "shop_id": inst.shop_id}


@api.post("/demo/reset", tags=["демо"])
def demo_reset(principal: Principal = Depends(get_principal), db: DbSession = Depends(get_session)) -> dict:
    if not principal.demo_shop_id:
        raise ApiError(403, "forbidden")
    ensure_template(db)
    db.commit()  # соединение — лимиту (см. demo_session)
    if principal.demo_install_id:
        _check_device_demo_limit(principal.demo_install_id)  # сброс тоже считается в лимит 3 в сутки
    shop = db.get(Shop, principal.demo_shop_id)
    _wipe_shop_data(db, shop.id)
    copy_template(db, shop.id, today_in(settings.default_timezone))
    db.commit()
    reportcache.invalidate(shop.id)  # AUD-12: данные отчётов изменились
    return {"shop_id": shop.id, "status": "reset"}


@api.get("/demo/price-list", tags=["шаблоны"])
def demo_price_list() -> Response:
    wb = Workbook()
    ws = wb.active
    ws.title = "Прайс-лист"
    ws.append(["Артикул", "Закупка, ₸", "Доставка до склада, ₸", "Упаковка, ₸", "Прочее, ₸", "Действует с"])
    for n in range(31, 41):
        ws.append([f"D{n:03d}", None, None, None, None, None])
    buf = io.BytesIO()
    wb.save(buf)
    return Response(content=buf.getvalue(), media_type="application/vnd.openxmlformats-officedocument."
                    "spreadsheetml.sheet", headers={"Content-Disposition": "attachment; filename=demo-price-list.xlsx"})


@api.get("/templates/costs", tags=["шаблоны"])
def costs_template() -> Response:
    wb = Workbook()
    ws = wb.active
    ws.title = "Затраты"
    ws.append(["Артикул", "Закупка, ₸", "Доставка до склада, ₸", "Упаковка, ₸", "Прочее, ₸", "Действует с"])
    buf = io.BytesIO()
    wb.save(buf)
    return Response(content=buf.getvalue(), media_type="application/vnd.openxmlformats-officedocument."
                    "spreadsheetml.sheet", headers={"Content-Disposition": "attachment; filename=costs-template.xlsx"})


def _check_device_demo_limit(install_id: str) -> None:
    """ADR-0005: не больше demo_per_device_per_day новых демо и сбросов в сутки с одного устройства.
    Счётчик в памяти процесса; при нескольких процессах его заменит общее хранилище лимитов (этап 1.15)."""
    if not allow(f"demo-dev:{install_id}", settings.demo_per_device_per_day, window=86400):
        raise ApiError(429, "rate_limited", "За сутки с этого устройства создано максимум демо-магазинов. Попробуйте завтра.")


def _record_terms(user) -> None:
    """1.19: фиксирует согласие с текущей версией условий и политики (версия и время)."""
    user.terms_version = settings.legal_version
    user.terms_accepted_at = utcnow()


def _purge_idle_demos(db: DbSession) -> None:
    # ADR-0005: демо живёт demo_lifetime_hours от создания (для записей без created_at — от последней активности)
    cutoff = utcnow() - timedelta(hours=settings.demo_lifetime_hours)
    expired = or_(DemoInstallation.created_at < cutoff,
                  and_(DemoInstallation.created_at.is_(None), DemoInstallation.last_active_at < cutoff))
    for inst in db.scalars(select(DemoInstallation).where(expired)).all():
        shop = db.get(Shop, inst.shop_id)
        if shop is not None:
            db.delete(shop)
        db.delete(inst)
    db.flush()


def _wipe_shop_data(db: DbSession, shop_id: str) -> None:
    wipe_shop_content(db, shop_id)  # AUD-26: одна реализация с удалением по хранению
    db.flush()


# ---------- пользователь ----------

class MeIn(BaseModel):
    name: str | None = Field(default=None, max_length=120)
    locale: Literal["ru", "kk"] | None = None


@api.get("/me", tags=["пользователь"], response_model=MeOut)
def me(principal: Principal = Depends(get_principal), db: DbSession = Depends(get_session)) -> dict:
    if principal.user_id is None:
        return {"demo": True, "email": None, "name": None, "locale": "ru"}
    user = current_user(principal, db)
    return {"demo": False, "id": user.id, "email": user.email, "name": user.name, "locale": user.locale,
            "age_confirmed": user.age_confirmed_at is not None,
            "terms_consent_required": user.terms_version != settings.legal_version}


@api.post("/me/terms", tags=["пользователь"])
def me_terms(body: TermsIn, principal: Principal = Depends(get_principal), db: DbSession = Depends(get_session)) -> dict:
    """1.19: согласие с текущей версией условий и политики. Без accepted=true — отказ."""
    user = current_user(principal, db)
    if body.accepted is not True:
        raise ApiError(422, "validation", "Нужно принять условия и политику конфиденциальности.")
    _record_terms(user)
    db.commit()
    return {"terms_version": user.terms_version, "accepted_at": user.terms_accepted_at.isoformat()}


@api.post("/me/age-confirm", tags=["пользователь"], response_model=AgeConfirmOut)
def age_confirm(principal: Principal = Depends(get_principal), db: DbSession = Depends(get_session)) -> dict:
    """Подтверждение возраста 18+ (ADR-0004). Без него магазин не создаётся."""
    user = current_user(principal, db)
    user.age_confirmed_at = _now()
    db.commit()
    return {"age_confirmed": True}


@api.patch("/me", tags=["пользователь"])
def me_update(body: MeIn, principal: Principal = Depends(get_principal), db: DbSession = Depends(get_session)) -> dict:
    user = current_user(principal, db)
    if body.name is not None:
        user.name = body.name
    if body.locale is not None:
        user.locale = body.locale
    db.commit()
    return me(principal, db)


@api.post("/me/deletion/start", status_code=202, tags=["пользователь"])
def deletion_start(principal: Principal = Depends(get_principal), db: DbSession = Depends(get_session)) -> dict:
    user = current_user(principal, db)
    code = new_code()
    db.add(AuthCode(email=user.email, purpose="delete", user_id=user.id, code_hash=hash_code(user.email, code),
                    expires_at=utcnow() + timedelta(minutes=settings.code_ttl_minutes)))
    db.commit()
    send_code_email(user.email, code, "delete")
    return {"status": "sent"}


class TermsIn(BaseModel):
    accepted: bool


class ConfirmIn(BaseModel):
    code: str = Field(min_length=6, max_length=6)


@api.post("/me/deletion/confirm", tags=["пользователь"])
def deletion_confirm(body: ConfirmIn, principal: Principal = Depends(get_principal),
                     db: DbSession = Depends(get_session)) -> dict:
    from .auth import aware

    user = current_user(principal, db)
    row = db.scalar(select(AuthCode).where(AuthCode.user_id == user.id, AuthCode.purpose == "delete",
                                           AuthCode.used.is_(False)).order_by(AuthCode.expires_at.desc()))
    if row is None or aware(row.expires_at) < utcnow() or hash_code(user.email, body.code) != row.code_hash:
        raise ApiError(400, "code_invalid")
    delete_user_account(db, user)  # AUD-08: все записи аккаунта, одна реализация для приложения и веба
    return {"status": "deleted"}


# ---------- магазины ----------

class ShopIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    timezone: str = settings.default_timezone
    language: Literal["ru", "kk"] = "ru"


@api.get("/shops", tags=["магазины"], response_model=ShopsOut)
def shops_list(principal: Principal = Depends(get_principal), db: DbSession = Depends(get_session)) -> dict:
    if principal.demo_shop_id:
        shop = db.get(Shop, principal.demo_shop_id)
        return {"items": [_shop_json(shop)]}
    rows = db.scalars(select(Shop).where(Shop.owner_user_id == principal.user_id)).all()
    return {"items": [_shop_json(s) for s in rows]}


@api.post("/shops", status_code=201, tags=["магазины"])
def shops_create(body: ShopIn, principal: Principal = Depends(get_principal), db: DbSession = Depends(get_session)) -> dict:
    user = current_user(principal, db)
    if user.age_confirmed_at is None:
        raise ApiError(403, "age_required", "Подтвердите, что вам 18 лет или больше.")
    if user.terms_version != settings.legal_version:
        raise ApiError(403, "terms_consent_required", "Примите обновлённые условия и политику конфиденциальности.")
    try:
        resolve("7d", body.timezone)
    except Exception as exc:  # noqa: BLE001
        raise ApiError(422, "validation", "Неизвестный часовой пояс.") from exc
    shop = Shop(owner_user_id=user.id, name=body.name, timezone=body.timezone, language=body.language)
    db.add(shop)
    db.commit()
    return _shop_json(shop)


class ShopPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    timezone: str | None = None
    language: Literal["ru", "kk"] | None = None


@api.patch("/shops/{shop_id}", tags=["магазины"])
def shops_patch(shop_id: str, body: ShopPatch, principal: Principal = Depends(get_principal),
                db: DbSession = Depends(get_session)) -> dict:
    shop = shop_for(db, principal, shop_id)
    if shop.is_demo:
        raise ApiError(403, "forbidden")
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(shop, k, v)
    db.commit()
    reportcache.invalidate(shop.id)  # AUD-12: данные отчётов изменились
    return _shop_json(shop)


def _shop_json(shop: Shop) -> dict:
    return {"id": shop.id, "name": shop.name, "timezone": shop.timezone, "language": shop.language,
            "is_demo": shop.is_demo}


# ---------- отчёты ----------

@api.get("/shops/{shop_id}/overview", tags=["обзор"], response_model=OverviewOut)
def get_overview(shop_id: str, period: str = Query("7d"), principal: Principal = Depends(get_principal),
                 db: DbSession = Depends(get_session)) -> dict:
    shop = shop_for(db, principal, shop_id)

    def compute() -> dict:
        data = load_shop(db, shop)
        return overview(data, build_facts(data), _period(period, shop), _now())

    return reportcache.memo(shop.id, f"overview|{period}|{_minute()}", compute)


@api.get("/shops/{shop_id}/profit-breakdown", tags=["обзор"], response_model=ProfitBreakdownOut)
def get_profit_breakdown(shop_id: str, period: str = Query("7d"), principal: Principal = Depends(get_principal),
                         db: DbSession = Depends(get_session)) -> dict:
    shop = shop_for(db, principal, shop_id)

    def compute() -> dict:
        data = load_shop(db, shop)
        return profit_breakdown(data, build_facts(data), _period(period, shop))

    return reportcache.memo(shop.id, f"profit|{period}|{_minute()}", compute)


@api.get("/shops/{shop_id}/orders", tags=["заказы"], response_model=OrdersPageOut)
def get_orders(shop_id: str, period: str = Query("7d"), status: str | None = None, q: str | None = None,
               cursor: str | None = None, limit: int = 50, principal: Principal = Depends(get_principal),
               db: DbSession = Depends(get_session)) -> dict:
    shop = shop_for(db, principal, shop_id)

    def compute() -> dict:
        data = load_shop(db, shop)
        return orders_list(data, _period(period, shop), status, q, _cursor(cursor), _limit(limit))

    key = f"orders|{period}|{status}|{q}|{cursor}|{limit}|{_minute()}"
    return reportcache.memo(shop.id, key, compute)


@api.get("/shops/{shop_id}/orders/{order_id}", tags=["заказы"], response_model=OrderDetailOut)
def get_order(shop_id: str, order_id: str, principal: Principal = Depends(get_principal),
              db: DbSession = Depends(get_session)) -> dict:
    shop = shop_for(db, principal, shop_id)
    order = db.get(Order, order_id)
    if order is None or order.shop_id != shop.id:
        raise ApiError(404, "not_found")
    data = load_shop(db, shop)
    return order_detail(data, build_facts(data), order)


@api.get("/shops/{shop_id}/products/missing-costs", tags=["товары"], response_model=MissingCostsOut)
def get_missing_costs(shop_id: str, principal: Principal = Depends(get_principal),
                      db: DbSession = Depends(get_session)) -> dict:
    shop = shop_for(db, principal, shop_id)
    return reportcache.memo(shop.id, f"missing|{_minute()}",
                            lambda: {"items": missing_costs_list(load_shop(db, shop))})


@api.get("/shops/{shop_id}/products", tags=["товары"], response_model=ProductsPageOut)
def get_products(shop_id: str, period: str = Query("30d"), filter: str | None = Query(None, alias="filter"),
                 sort: str = "profit_desc", q: str | None = None, cursor: str | None = None, limit: int = 50,
                 principal: Principal = Depends(get_principal), db: DbSession = Depends(get_session)) -> dict:
    shop = shop_for(db, principal, shop_id)

    def compute() -> dict:
        data = load_shop(db, shop)
        return products_list(data, build_facts(data), _period(period, shop), filter, sort, q,
                             _cursor(cursor), _limit(limit))

    key = f"products|{period}|{filter}|{sort}|{q}|{cursor}|{limit}|{_minute()}"
    return reportcache.memo(shop.id, key, compute)


# ---------- подписка (ТЗ 2.1, раздел 8) ----------

@api.get("/shops/{shop_id}/subscription", tags=["подписка"], response_model=SubscriptionOut)
def get_subscription_state(shop_id: str, principal: Principal = Depends(get_principal),
                           db: DbSession = Depends(get_session)) -> dict:
    shop = shop_for(db, principal, shop_id, guard_access=False)
    body = subscription_view(db, shop)
    # Пробный период доступен, если подписки у магазина не было и отметки защиты отсутствуют (раздел 8.2).
    account_key = _account_key(db, principal)
    body["trial_available"] = (get_subscription(db, shop.id) is None
                               and trial_eligible(db, account_key, None))
    return body


def _account_key(db: DbSession, principal: Principal) -> str | None:
    """Ключ аккаунта для защиты пробного периода: нормализованный email."""
    if principal.user_id is None:
        return None
    return current_user(principal, db).email.strip().lower()


@api.post("/shops/{shop_id}/subscription/trial", status_code=201, tags=["подписка"], response_model=SubscriptionOut)
def post_start_trial(shop_id: str, principal: Principal = Depends(get_principal),
                     db: DbSession = Depends(get_session)) -> dict:
    """Пробный период. В боевом режиме выдаётся только после подтверждения магазина приложений (раздел 8.2)."""
    shop = shop_for(db, principal, shop_id, guard_access=False)
    if not settings.billing_test_mode:
        raise ApiError(501, "store_not_configured", "Оформление через App Store и Google Play ещё не подключено.")
    start_trial(db, shop, _account_key(db, principal), None)
    return subscription_view(db, shop)


@api.post("/shops/{shop_id}/subscription/verify", tags=["подписка"])
def post_verify_purchase(shop_id: str, principal: Principal = Depends(get_principal),
                         db: DbSession = Depends(get_session)) -> dict:
    """Проверка покупки через App Store Server API и Google Play Developer API (раздел 8.5).
    Не подключено: нужны аккаунты владельца (spec-2.1, 19.3 и 19.10)."""
    shop_for(db, principal, shop_id, guard_access=False)
    raise ApiError(501, "store_not_configured", "Проверка покупок ещё не подключена.")


XLSX_MEDIA = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@api.get("/shops/{shop_id}/exports/profit.xlsx", tags=["выгрузки"])
def export_profit_xlsx(shop_id: str, period: str = Query("30d"), principal: Principal = Depends(get_principal),
                       db: DbSession = Depends(get_session)) -> Response:
    """Отчёт о прибыли в Excel (ТЗ 2.1, 9.5). Итоги совпадают с экраном: те же функции расчёта."""
    shop = shop_for(db, principal, shop_id)
    data = load_shop(db, shop)
    p = _period(period, shop)
    content = profit_workbook(data, build_facts(data), p, _now())
    return Response(content=content, media_type=XLSX_MEDIA,
                    headers={"Content-Disposition": f'attachment; filename="{profit_filename(p)}"'})


@api.get("/me/export", tags=["пользователь"])
def export_my_data(principal: Principal = Depends(get_principal), db: DbSession = Depends(get_session)) -> Response:
    """«Скачать мои данные» (ТЗ 2.1, 9.4). Файл строится сразу и не хранится на сервере. До 3 выгрузок в сутки."""
    if principal.user_id is None:
        raise ApiError(403, "account_required", "Выгрузка доступна после входа по почте или через Apple/Google.")
    user = current_user(principal, db)
    if not allow(f"export:{user.id}", 3, 86_400):
        raise ApiError(429, "rate_limited", "Выгрузок слишком много. Попробуйте завтра.")
    content = user_export_zip(db, user)
    stamp = _now().strftime("%Y%m%d")
    return Response(content=content, media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="satti-moi-dannye-{stamp}.zip"'})


@api.get("/shops/{shop_id}/products/{product_id}", tags=["товары"], response_model=ProductDetailOut)
def get_product(shop_id: str, product_id: str, period: str = Query("30d"),
                principal: Principal = Depends(get_principal), db: DbSession = Depends(get_session)) -> dict:
    shop = shop_for(db, principal, shop_id)
    product = db.get(Product, product_id)
    if product is None or product.shop_id != shop.id:
        raise ApiError(404, "not_found")
    data = load_shop(db, shop)
    return product_detail(data, build_facts(data), product, _period(period, shop), _now())


# ---------- затраты ----------

class CostIn(BaseModel):
    purchase: str  # сумма в тенге строкой, например "2800" или "2800.50"
    delivery_to_warehouse: str = "0"
    packaging: str = "0"
    other: str = "0"
    apply_to_history: bool | None = None  # None — по правилам раздела 7.5
    effective_from: date | None = None


def _minor(value: str) -> int:
    from .money import parse_tenge_to_minor

    try:
        m = parse_tenge_to_minor(value)
    except ValueError as exc:
        raise ApiError(422, "validation", str(exc)) from exc
    if m < 0:
        raise ApiError(422, "validation", "Отрицательные значения не допускаются.")
    return m


def _add_cost(db: DbSession, shop: Shop, product: Product, body: CostIn, source: str,
              batch_id: str | None = None) -> ProductCostVersion:
    versions = db.scalars(select(ProductCostVersion).where(ProductCostVersion.product_id == product.id,
                                                           ProductCostVersion.cancelled.is_(False))).all()
    today = today_in(shop.timezone)
    if body.effective_from is not None:
        eff = body.effective_from
    elif not versions:
        eff = None if (body.apply_to_history in (None, True)) else today
    else:
        eff = today
    v = ProductCostVersion(
        shop_id=shop.id, product_id=product.id,
        purchase_minor=_minor(body.purchase),
        delivery_to_warehouse_minor=_minor(body.delivery_to_warehouse),
        packaging_minor=_minor(body.packaging),
        other_minor=_minor(body.other),
        effective_from=eff, source=source, import_batch_id=batch_id,
    )
    db.add(v)
    db.flush()
    return v


@api.get("/shops/{shop_id}/products/{product_id}/cost-versions", tags=["затраты"], response_model=CostVersionsOut)
def cost_versions(shop_id: str, product_id: str, principal: Principal = Depends(get_principal),
                  db: DbSession = Depends(get_session)) -> dict:
    shop = shop_for(db, principal, shop_id)
    rows = db.scalars(select(ProductCostVersion).where(ProductCostVersion.product_id == product_id,
                                                       ProductCostVersion.shop_id == shop.id)
                      .order_by(ProductCostVersion.created_at)).all()
    return {"items": [_version_json(v) for v in rows]}


@api.post("/shops/{shop_id}/products/{product_id}/cost-versions", status_code=201, tags=["затраты"])
def cost_version_create(shop_id: str, product_id: str, body: CostIn,
                        principal: Principal = Depends(get_principal), db: DbSession = Depends(get_session)) -> dict:
    shop = shop_for(db, principal, shop_id)
    product = db.get(Product, product_id)
    if product is None or product.shop_id != shop.id:
        raise ApiError(404, "not_found")
    # QA-06: повтор той же отправки в течение минуты (двойной тап, повтор сети) не создаёт вторую версию
    values = (_minor(body.purchase), _minor(body.delivery_to_warehouse), _minor(body.packaging), _minor(body.other))
    recent = db.scalar(select(ProductCostVersion).where(
        ProductCostVersion.shop_id == shop.id, ProductCostVersion.product_id == product.id,
        ProductCostVersion.cancelled.is_(False),
        ProductCostVersion.created_at >= datetime.now(timezone.utc) - timedelta(seconds=60),
    ).order_by(ProductCostVersion.created_at.desc()).limit(1))
    if recent is not None and (recent.purchase_minor, recent.delivery_to_warehouse_minor,
                               recent.packaging_minor, recent.other_minor) == values \
            and (body.effective_from is None or recent.effective_from == body.effective_from):
        return _version_json(recent)
    v = _add_cost(db, shop, product, body, "manual")
    db.commit()
    reportcache.invalidate(shop.id)  # AUD-12: данные отчётов изменились
    return _version_json(v)


@api.post("/shops/{shop_id}/cost-versions/{version_id}/cancel", tags=["затраты"])
def cost_version_cancel(shop_id: str, version_id: str, principal: Principal = Depends(get_principal),
                        db: DbSession = Depends(get_session)) -> dict:
    """Отмена версии затрат: кнопка «Отменить» в тосте после сохранения (docs/design.md, 12.10)."""
    shop = shop_for(db, principal, shop_id)
    v = db.get(ProductCostVersion, version_id)
    if v is None or v.shop_id != shop.id:
        raise ApiError(404, "not_found")
    v.cancelled = True
    db.commit()
    reportcache.invalidate(shop.id)  # AUD-12: данные отчётов изменились
    return {"id": v.id, "cancelled": True}


class BulkCostItem(BaseModel):
    product_id: str
    purchase: str
    delivery_to_warehouse: str = "0"
    packaging: str = "0"
    other: str = "0"


class BulkCostIn(BaseModel):
    items: list[BulkCostItem] = Field(min_length=1, max_length=200)
    apply_to_history: bool = True


@api.post("/shops/{shop_id}/cost-versions/bulk", tags=["затраты"])
def cost_bulk(shop_id: str, body: BulkCostIn, principal: Principal = Depends(get_principal),
              db: DbSession = Depends(get_session)) -> dict:
    shop = shop_for(db, principal, shop_id)
    created = 0
    for item in body.items:
        product = db.get(Product, item.product_id)
        if product is None or product.shop_id != shop.id:
            raise ApiError(404, "not_found")
        _add_cost(db, shop, product, CostIn(**item.model_dump(exclude={"product_id"}),
                                            apply_to_history=body.apply_to_history), "manual")
        created += 1
    db.commit()
    reportcache.invalidate(shop.id)  # AUD-12: данные отчётов изменились
    return {"saved": created}


def _version_json(v: ProductCostVersion) -> dict:
    return {
        "id": v.id,
        "purchase_minor": v.purchase_minor,
        "delivery_to_warehouse_minor": v.delivery_to_warehouse_minor,
        "packaging_minor": v.packaging_minor,
        "other_minor": v.other_minor,
        "landed_unit_minor": v.landed_unit_minor,
        "effective_from": v.effective_from.isoformat() if v.effective_from else None,
        "source": v.source,
        "cancelled": v.cancelled,
    }


# ---------- комиссии и расходы ----------

class CommissionIn(BaseModel):
    category: str = Field(min_length=1, max_length=120)
    rate_percent: str  # например "10" или "7,5"
    effective_from: date | None = None


@api.get("/shops/{shop_id}/commissions", tags=["комиссии"], response_model=CommissionsOut)
def commissions_list(shop_id: str, principal: Principal = Depends(get_principal),
                     db: DbSession = Depends(get_session)) -> dict:
    shop = shop_for(db, principal, shop_id)
    rows = db.scalars(select(CommissionPreset).where(CommissionPreset.shop_id == shop.id)).all()
    return {"items": [{"id": r.id, "category": r.category, "rate_bp": r.rate_bp,
                       "effective_from": r.effective_from.isoformat() if r.effective_from else None,
                       "source": r.source, "verified": r.verified, "demo": r.demo} for r in rows]}


@api.post("/shops/{shop_id}/commissions", status_code=201, tags=["комиссии"], response_model=CommissionCreatedOut)
def commissions_create(shop_id: str, body: CommissionIn, principal: Principal = Depends(get_principal),
                       db: DbSession = Depends(get_session)) -> dict:
    from decimal import Decimal, InvalidOperation

    shop = shop_for(db, principal, shop_id)
    try:
        pct = Decimal(body.rate_percent.replace(",", ".").strip())
    except InvalidOperation as exc:
        raise ApiError(422, "validation", "Укажите ставку в процентах.") from exc
    if pct < 0 or pct > 100 or (pct * 100) != (pct * 100).to_integral_value():
        raise ApiError(422, "validation", "Ставка от 0 до 100% с точностью до сотых процента.")
    preset = CommissionPreset(shop_id=shop.id, category=body.category, rate_bp=int(pct * 100),
                              effective_from=body.effective_from, source="manual", verified=False, demo=False)
    db.add(preset)
    db.commit()
    reportcache.invalidate(shop.id)  # AUD-12: данные отчётов изменились
    return {"id": preset.id, "rate_bp": preset.rate_bp}


# ---------- налог (ТЗ 2.1, раздел 7) ----------

class TaxIn(BaseModel):
    enabled: bool
    rate_percent: str | None = None  # "4", "1,5"; от 0 до 30 с одним знаком после запятой
    effective_from: date | None = None  # None — ко всей истории


def _tax_row(t) -> dict:
    return {"id": t.id, "enabled": t.rate_bp is not None,
            "rate_bp": t.rate_bp,
            "effective_from": t.effective_from.isoformat() if t.effective_from else None,
            "created_at": t.created_at.isoformat()}


@api.get("/shops/{shop_id}/tax", tags=["налог"], response_model=TaxOut)
def tax_get(shop_id: str, principal: Principal = Depends(get_principal),
            db: DbSession = Depends(get_session)) -> dict:
    from .models import TaxRate

    shop = shop_for(db, principal, shop_id)
    rows = db.scalars(select(TaxRate).where(TaxRate.shop_id == shop.id)).all()
    rows = sorted(rows, key=lambda t: (t.effective_from or date.min, t.created_at), reverse=True)
    return {"current": _tax_row(rows[0]) if rows else None, "items": [_tax_row(t) for t in rows]}


@api.post("/shops/{shop_id}/tax", status_code=201, tags=["налог"])
def tax_set(shop_id: str, body: TaxIn, principal: Principal = Depends(get_principal),
            db: DbSession = Depends(get_session)) -> dict:
    from decimal import Decimal, InvalidOperation

    from .models import TaxRate

    shop = shop_for(db, principal, shop_id)
    rate_bp: int | None = None
    if body.enabled:
        try:
            pct = Decimal((body.rate_percent or "").replace(",", ".").strip())
        except InvalidOperation as exc:
            raise ApiError(422, "validation", "Укажите ставку в процентах.") from exc
        if pct < 0 or pct > 30 or (pct * 10) != (pct * 10).to_integral_value():
            raise ApiError(422, "validation", "Ставка от 0 до 30% с одним знаком после запятой.")
        rate_bp = int(pct * 100)
    row = TaxRate(shop_id=shop.id, rate_bp=rate_bp, effective_from=body.effective_from)
    db.add(row)
    db.commit()
    reportcache.invalidate(shop.id)  # AUD-12: данные отчётов изменились
    return _tax_row(row)


class ExpenseIn(BaseModel):
    kind: Literal["ads", "other"]
    amount: str
    period_start: date
    period_end: date


@api.get("/shops/{shop_id}/expenses", tags=["расходы"], response_model=ExpensesOut)
def expenses_list(shop_id: str, principal: Principal = Depends(get_principal),
                  db: DbSession = Depends(get_session)) -> dict:
    shop = shop_for(db, principal, shop_id)
    rows = db.scalars(select(ExpenseEntry).where(ExpenseEntry.shop_id == shop.id)).all()
    return {"items": [{"id": r.id, "kind": r.kind, "amount_minor": r.amount_minor,
                       "period_start": r.period_start.isoformat(), "period_end": r.period_end.isoformat()}
                      for r in rows]}


@api.post("/shops/{shop_id}/expenses", status_code=201, tags=["расходы"])
def expenses_create(shop_id: str, body: ExpenseIn, principal: Principal = Depends(get_principal),
                    db: DbSession = Depends(get_session)) -> dict:
    shop = shop_for(db, principal, shop_id)
    if body.period_end < body.period_start:
        raise ApiError(422, "validation", "Конец периода раньше начала.")
    e = ExpenseEntry(shop_id=shop.id, kind=body.kind, amount_minor=_minor(body.amount),
                     period_start=body.period_start, period_end=body.period_end, source="manual")
    db.add(e)
    db.commit()
    reportcache.invalidate(shop.id)  # AUD-12: данные отчётов изменились
    return {"id": e.id}


@api.delete("/shops/{shop_id}/expenses/{expense_id}", status_code=204, tags=["расходы"])
def expenses_delete(shop_id: str, expense_id: str, principal: Principal = Depends(get_principal),
                    db: DbSession = Depends(get_session)) -> Response:
    shop = shop_for(db, principal, shop_id)
    e = db.get(ExpenseEntry, expense_id)
    if e is None or e.shop_id != shop.id:
        raise ApiError(404, "not_found")
    db.delete(e)
    db.commit()
    reportcache.invalidate(shop.id)  # AUD-12: данные отчётов изменились
    return Response(status_code=204)


# ---------- импорт ----------

def _batch(db: DbSession, shop: Shop, batch_id: str) -> ImportBatch:
    b = db.get(ImportBatch, batch_id)
    if b is None or b.shop_id != shop.id:
        raise ApiError(404, "not_found")
    return b


@api.post("/shops/{shop_id}/imports", status_code=201, tags=["импорт"])
async def import_upload(shop_id: str, file: UploadFile = File(...),
                        principal: Principal = Depends(get_principal), db: DbSession = Depends(get_session)) -> dict:
    shop = shop_for(db, principal, shop_id)
    # AUD-07: лимит на аккаунт (или демо-установку), а не на сессию: обновление токена создаёт новую сессию
    key = f"imp:{principal.user_id or principal.demo_install_id or principal.session_id}"
    if not allow(key, settings.import_requests_per_hour):
        raise ApiError(429, "rate_limited")
    content = await file.read(settings.import_max_bytes + 1)
    # AUD-06: разбор файла — в пуле потоков, чтобы не занимать цикл событий сервера
    parsed = await run_in_threadpool(parse_file, file.filename or "file", content)
    mapping = auto_mapping(parsed.columns)
    batch = ImportBatch(shop_id=shop.id, filename=(file.filename or "file")[:255], status="uploaded",
                        rows_total=len(parsed.rows), payload=dump_payload(parsed))
    db.add(batch)
    db.commit()
    sample = [[str(c) if c is not None else "" for c in r.cells] for r in parsed.rows[:3]]
    return {"id": batch.id, "filename": batch.filename, "columns": parsed.columns, "rows_total": len(parsed.rows),
            "mapping": mapping, "missing_required": missing_required(mapping), "fields": FIELDS, "sample": sample}


class MappingIn(BaseModel):
    mapping: dict[str, str | None]
    duplicates: Literal["skip", "last"] = "skip"


@api.put("/shops/{shop_id}/imports/{import_id}/mapping", tags=["импорт"])
def import_mapping(shop_id: str, import_id: str, body: MappingIn, principal: Principal = Depends(get_principal),
                   db: DbSession = Depends(get_session)) -> dict:
    shop = shop_for(db, principal, shop_id)
    batch = _batch(db, shop, import_id)
    if batch.status not in ("uploaded", "previewed"):
        raise ApiError(409, "validation", "Загрузка уже применена или отменена.")
    unknown = set(body.mapping) - set(FIELDS)
    if unknown:
        raise ApiError(422, "validation", "Неизвестные поля сопоставления.")
    if missing_required(body.mapping):
        raise ApiError(422, "validation", "Укажите колонки для артикула и закупки.")
    payload = load_payload(batch.payload)
    if any(v and v not in payload.columns for v in body.mapping.values()):
        raise ApiError(422, "validation", "В файле нет такой колонки.")
    import json

    batch.payload = json.dumps({**json.loads(batch.payload), "mapping": body.mapping,
                                "duplicates": body.duplicates}, ensure_ascii=False)
    batch.status = "previewed"
    db.commit()
    reportcache.invalidate(shop.id)  # AUD-12: данные отчётов изменились
    return {"status": "ok"}


def _preview_data(db: DbSession, shop: Shop, batch: ImportBatch) -> dict:
    import json

    stored = json.loads(batch.payload)
    parsed = load_payload(batch.payload)
    mapping = stored.get("mapping") or auto_mapping(parsed.columns)
    if missing_required(mapping):
        raise ApiError(422, "validation", "Сначала укажите сопоставление колонок.")
    products = {p.sku: p for p in db.scalars(select(Product).where(Product.shop_id == shop.id)).all()}
    valid, errors, total = validate_rows(parsed, mapping, stored.get("duplicates", "skip"), set(products))
    kinds = {"new": 0, "updated": 0, "unchanged": 0}
    for v in valid:
        p = products[v.sku]
        current = db.scalars(select(ProductCostVersion).where(ProductCostVersion.product_id == p.id,
                                                              ProductCostVersion.cancelled.is_(False))
                             .order_by(ProductCostVersion.created_at)).all()
        if not current:
            kinds["new"] += 1
        else:
            last = current[-1]
            same = (last.purchase_minor, last.delivery_to_warehouse_minor, last.packaging_minor,
                    last.other_minor) == (v.purchase_minor, v.delivery_to_warehouse_minor,
                                          v.packaging_minor, v.other_minor)
            kinds["unchanged" if same else "updated"] += 1
    return {
        "total_rows": total,
        "valid_rows": len(valid),
        "counts": kinds,
        "errors_count": len(errors),
        "errors": [{"row": e.number, "sku": e.sku, "field": e.field, "message": e.message} for e in errors[:200]],
        "new_products_without_cost": kinds["new"],
        "coverage_after": None,
        "valid": [v.__dict__ for v in valid],
        "errors_all": errors,
        "status": batch.status,
    }


@api.get("/shops/{shop_id}/imports/{import_id}/preview", tags=["импорт"])
def import_preview(shop_id: str, import_id: str, principal: Principal = Depends(get_principal),
                   db: DbSession = Depends(get_session)) -> dict:
    shop = shop_for(db, principal, shop_id)
    batch = _batch(db, shop, import_id)
    data = _preview_data(db, shop, batch)
    data.pop("valid", None)
    data.pop("errors_all", None)
    data["status"] = batch.status
    return data


class ApplyIn(BaseModel):
    apply_to_history: bool | None = None
    effective_from: date | None = None


@api.post("/shops/{shop_id}/imports/{import_id}/apply", tags=["импорт"])
def import_apply(shop_id: str, import_id: str, body: ApplyIn, principal: Principal = Depends(get_principal),
                 db: DbSession = Depends(get_session)) -> dict:
    shop = shop_for(db, principal, shop_id)
    batch = _batch(db, shop, import_id)
    if batch.status != "previewed":
        raise ApiError(409, "validation", "Сначала проверьте загрузку.")
    data = _preview_data(db, shop, batch)
    products = {p.sku: p for p in db.scalars(select(Product).where(Product.shop_id == shop.id)).all()}
    today = today_in(shop.timezone)
    for v in data["valid"]:
        product = products[v["sku"]]
        eff_date = date.fromisoformat(v["effective_from"]) if v["effective_from"] else None
        has_versions = db.scalar(select(ProductCostVersion.id).where(
            ProductCostVersion.product_id == product.id, ProductCostVersion.cancelled.is_(False)).limit(1))
        if eff_date is None:
            if has_versions:
                eff_date = body.effective_from or today
            else:
                eff_date = body.effective_from or (None if body.apply_to_history in (None, True) else today)
        db.add(ProductCostVersion(
            shop_id=shop.id, product_id=product.id,
            purchase_minor=v["purchase_minor"], delivery_to_warehouse_minor=v["delivery_to_warehouse_minor"],
            packaging_minor=v["packaging_minor"], other_minor=v["other_minor"],
            effective_from=eff_date, source="import", import_batch_id=batch.id,
        ))
    batch.status = "applied"
    batch.applied_at = utcnow()
    db.commit()
    reportcache.invalidate(shop.id)  # AUD-12: данные отчётов изменились
    return {"status": "applied", "applied_rows": len(data["valid"]), "errors_count": data["errors_count"]}


@api.post("/shops/{shop_id}/imports/{import_id}/undo", tags=["импорт"])
def import_undo(shop_id: str, import_id: str, principal: Principal = Depends(get_principal),
                db: DbSession = Depends(get_session)) -> dict:
    shop = shop_for(db, principal, shop_id)
    batch = _batch(db, shop, import_id)
    if batch.status != "applied":
        raise ApiError(409, "validation", "Отменить можно только применённую загрузку.")
    latest = db.scalar(select(ImportBatch).where(ImportBatch.shop_id == shop.id, ImportBatch.status == "applied")
                       .order_by(ImportBatch.applied_at.desc()))
    if latest is None or latest.id != batch.id:
        raise ApiError(409, "validation", "Отменить можно только последнюю загрузку.")
    for v in db.scalars(select(ProductCostVersion).where(ProductCostVersion.import_batch_id == batch.id)).all():
        v.cancelled = True
    batch.status = "undone"
    batch.undone_at = utcnow()
    db.commit()
    reportcache.invalidate(shop.id)  # AUD-12: данные отчётов изменились
    return {"status": "undone"}


@api.get("/shops/{shop_id}/imports/{import_id}/errors", tags=["импорт"])
def import_errors(shop_id: str, import_id: str, principal: Principal = Depends(get_principal),
                  db: DbSession = Depends(get_session)) -> PlainTextResponse:
    shop = shop_for(db, principal, shop_id)
    batch = _batch(db, shop, import_id)
    data = _preview_data(db, shop, batch)
    csv_text = errors_csv(data["errors_all"])
    return PlainTextResponse(csv_text, media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": "attachment; filename=import-errors.csv"})


# ---------- ИИ ----------

class ConsentIn(BaseModel):
    granted: bool


@api.get("/ai/quota", tags=["ИИ"], response_model=AIQuotaOut)
def ai_quota(shop_id: str, principal: Principal = Depends(get_principal), db: DbSession = Depends(get_session)) -> dict:
    shop = shop_for(db, principal, shop_id)
    remaining = ai_service.check_quota(db, principal.user_id, shop.id, _now())
    version, active = ai_consent_state(db, principal)
    return {"limit": settings.ai_daily_limit, "remaining": remaining, "consent_active": active,
            "consent_version": version}


@api.post("/ai/consent", tags=["ИИ"])
def ai_consent_set(body: ConsentIn, principal: Principal = Depends(get_principal),
                   db: DbSession = Depends(get_session)) -> dict:
    set_ai_consent(db, principal, body.granted)
    db.commit()
    version, active = ai_consent_state(db, principal)
    return {"consent_active": active, "consent_version": version, "service": settings.ai_service_name}


class AskIn(BaseModel):
    question: str = Field(min_length=1, max_length=500)
    conversation_id: str | None = None


@api.post("/shops/{shop_id}/ai/ask", tags=["ИИ"])
def ai_ask(shop_id: str, body: AskIn, principal: Principal = Depends(get_principal),
           db: DbSession = Depends(get_session)) -> dict:
    shop = shop_for(db, principal, shop_id)
    require_ai(db)  # выключатель ИИ (QA-02)
    _, active = ai_consent_state(db, principal)
    if not active:
        raise ApiError(403, "ai_consent_required")
    # AUD-17: проверка квоты и запись вопроса — под одной блокировкой на субъекта квоты
    with quota_guard(principal.user_id or shop.id):
        ai_service.require_budget(db, _now())  # бюджет ИИ (QA-03)
        ai_service.check_quota(db, principal.user_id, shop.id, _now())
        result = ai_service.ask(db, shop, body.question, principal.user_id, body.conversation_id)
        db.commit()
    return result


@api.get("/ai/conversations", tags=["ИИ"])
def ai_conversations(shop_id: str, principal: Principal = Depends(get_principal),
                     db: DbSession = Depends(get_session)) -> dict:
    shop = shop_for(db, principal, shop_id)
    rows = db.scalars(select(AIConversation).where(AIConversation.shop_id == shop.id)
                      .order_by(AIConversation.created_at.desc())).all()
    return {"items": [{"id": c.id, "title": c.title, "created_at": c.created_at.isoformat()} for c in rows]}


@api.get("/ai/conversations/{conversation_id}", tags=["ИИ"])
def ai_conversation(conversation_id: str, principal: Principal = Depends(get_principal),
                    db: DbSession = Depends(get_session)) -> dict:
    conv = db.get(AIConversation, conversation_id)
    if conv is None:
        raise ApiError(404, "not_found")
    shop_for(db, principal, conv.shop_id)
    turns = db.scalars(select(AITurn).where(AITurn.conversation_id == conv.id).order_by(AITurn.created_at)).all()
    import json

    return {"id": conv.id, "title": conv.title, "turns": [
        {"id": t.id, "question": t.question, "answer": json.loads(t.answer_json)} for t in turns]}


@api.delete("/ai/conversations/{conversation_id}", status_code=204, tags=["ИИ"])
def ai_conversation_delete(conversation_id: str, principal: Principal = Depends(get_principal),
                           db: DbSession = Depends(get_session)) -> Response:
    conv = db.get(AIConversation, conversation_id)
    if conv is None:
        raise ApiError(404, "not_found")
    shop_for(db, principal, conv.shop_id)
    db.delete(conv)
    db.commit()
    return Response(status_code=204)


class FeedbackIn(BaseModel):
    shop_id: str
    turn_id: str | None = None
    kind: Literal["up", "down", "flag"]
    reason: str | None = Field(default=None, max_length=64)
    comment: str | None = Field(default=None, max_length=500)


@api.post("/ai/feedback", status_code=201, tags=["ИИ"])
def ai_feedback(body: FeedbackIn, principal: Principal = Depends(get_principal),
                db: DbSession = Depends(get_session)) -> dict:
    shop = shop_for(db, principal, body.shop_id)
    fb = ai_service.record_feedback(db, shop, body.turn_id, body.kind, body.reason, body.comment)
    db.commit()
    return {"id": fb.id}


def _metered_draft(db: DbSession, principal: Principal, shop: Shop, make) -> dict:
    """Черновик ИИ: та же квота и бюджет, что у вопросов (QA-04). Списывается только успешный черновик."""
    with quota_guard(principal.user_id or shop.id):
        ai_service.require_budget(db, _now())
        ai_service.check_quota(db, principal.user_id, shop.id, _now())
        result = make()  # при ошибке ввода (422) квота не тратится
        ai_service.record_usage(db, principal.user_id, shop.id, _now(), "draft")
        db.commit()
    result["generatedBy"] = "ai"  # QA-05
    return result


@api.post("/ai/product-drafts", status_code=201, tags=["ИИ"])
async def ai_product_draft(shop_id: str = Form(...), facts: str = Form(...), languages: str = Form("ru"),
                           photos: list[UploadFile] = File(default=[]),
                           principal: Principal = Depends(get_principal),
                           db: DbSession = Depends(get_session)) -> dict:
    shop = shop_for(db, principal, shop_id)  # проверка доступа к магазину
    require_ai(db)  # выключатель ИИ (QA-02)
    _, active = ai_consent_state(db, principal)
    if not active:
        raise ApiError(403, "ai_consent_required")
    if len(photos) > 5:
        raise ApiError(422, "validation", "Можно добавить не больше 5 фото.")
    for ph in photos:
        head = await ph.read(16)
        await ph.seek(0)
        if not (head.startswith(b"\xff\xd8\xff") or head.startswith(b"\x89PNG") or head[:4] == b"RIFF"):
            raise ApiError(422, "validation", "Фото должно быть в формате JPG, PNG или WebP.")
    # Фото не сохраняются: читаются только для проверки формата и удаляются вместе с запросом.
    return await run_in_threadpool(_metered_draft, db, principal, shop, lambda: ai_service.product_draft(facts, languages, len(photos)))


class ReplyDraftIn(BaseModel):
    question: str = Field(min_length=1, max_length=500)
    tone: Literal["polite", "short"] = "polite"


@api.post("/ai/reply-drafts", status_code=201, tags=["ИИ"])
def ai_reply_draft(body: ReplyDraftIn, shop_id: str = Query(...), principal: Principal = Depends(get_principal),
                   db: DbSession = Depends(get_session)) -> dict:
    shop = shop_for(db, principal, shop_id)
    require_ai(db)  # выключатель ИИ (QA-02)
    _, active = ai_consent_state(db, principal)
    if not active:
        raise ApiError(403, "ai_consent_required")
    return _metered_draft(db, principal, shop, lambda: ai_service.reply_draft(body.question, body.tone))


# ---------- уведомления и Kaspi (за флагом) ----------

class PushIn(BaseModel):
    token: str = Field(min_length=8, max_length=512)
    platform: Literal["ios", "android"]


@api.post("/devices/push-token", status_code=204, tags=["уведомления"])
def push_token(body: PushIn, principal: Principal = Depends(get_principal)) -> Response:
    # Отправка push-уведомлений включается на этапе B (раздел 3.8 ТЗ). Токен сейчас не сохраняется.
    return Response(status_code=204)


class NotifIn(BaseModel):
    product_in_minus: bool | None = None
    weekly_summary: bool | None = None
    quiet_hours: bool | None = None


@api.patch("/notification-settings", tags=["уведомления"])
def notification_settings(body: NotifIn, principal: Principal = Depends(get_principal),
                          db: DbSession = Depends(get_session)) -> dict:
    user = current_user(principal, db)
    row = db.get(NotificationSettings, user.id) or NotificationSettings(user_id=user.id)
    db.add(row)
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(row, k, v)
    db.commit()
    return {"product_in_minus": row.product_in_minus, "weekly_summary": row.weekly_summary,
            "quiet_hours": row.quiet_hours}


def _kaspi_disabled() -> ApiError:
    return ApiError(404, "not_found", "Подключение Kaspi будет доступно позже.")


@api.post("/shops/{shop_id}/kaspi/connection", tags=["Kaspi"])
def kaspi_connect(shop_id: str, principal: Principal = Depends(get_principal)) -> dict:
    raise _kaspi_disabled()


@api.get("/shops/{shop_id}/kaspi/connection", tags=["Kaspi"])
def kaspi_status(shop_id: str, principal: Principal = Depends(get_principal)) -> dict:
    if not settings.kaspi_connection_enabled:
        return {"enabled": False, "status": "not_connected"}
    raise _kaspi_disabled()


@api.delete("/shops/{shop_id}/kaspi/connection", tags=["Kaspi"])
def kaspi_disconnect(shop_id: str, principal: Principal = Depends(get_principal)) -> dict:
    raise _kaspi_disabled()
