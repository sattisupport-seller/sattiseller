"""HTTP-маршруты Satti API /v1 (docs/spec.md, раздел 5.2)."""

from __future__ import annotations
import logging
import os
from decimal import Decimal, InvalidOperation
import json

import io
from datetime import date, datetime, timedelta, timezone
from .timeutil import utc_now
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, Header, Query, Request, Response, UploadFile
from fastapi.responses import PlainTextResponse
from openpyxl import Workbook
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel, Field
from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DbSession

from . import ai as ai_service
from . import draft_ai
from . import audit
from .accounts import delete_user_account
from . import accounts as accounts_service
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
from . import analytics as analytics_service
from . import kaspi as kaspi_service
from . import presentation as presentation_service
from .kaspi_client import KaspiAuthError, KaspiClient, KaspiUnavailable
from .errors import ApiError, pick_lang
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
from .mailer import MailError, send_code_email
from .stock import ENDING_SOON_DAYS, stock_push_mock, stock_states
from .models import (
    AIConversation,
    AITurn,
    AuthCode,
    ProductStock,
    CommissionPreset,
    DemoInstallation,
    ExpenseEntry,
    ImportBatch,
    NotificationSettings,
    Order,
    Product,
    ProductCostVersion,
    Session,
    KaspiConnection,
    Shop,
    User,
)
from .periods import Period, PeriodError, resolve, today_in
from . import billing, device_trust, push, seller_access, store_billing  # noqa: F401 — push: таблицы для create_all
from .billing import get_subscription, start_trial, subscription_view, trial_decision, wipe_shop_content
from .device_trust import DeviceVerdict
from .models import AIUsageEvent, AuditEvent
import hmac
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
    base_for,
    order_detail,
    orders_list,
    overview,
    products_list,
    product_detail,
    profit_breakdown,
    missing_costs as missing_costs_list,
)
from .security import hash_code, hash_device_id, new_code

log = logging.getLogger(__name__)
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
    return utc_now()


def _minute() -> str:
    """Ключ времени для кэша отчётов: минута (AUD-12)."""
    return _now().strftime("%Y-%m-%dT%H:%M")


# ---------- служебное ----------

@api.get("/app/config", response_model=AppConfig, tags=["служебное"])
def app_config(db: DbSession = Depends(get_session)) -> AppConfig:
    cfg = get_app_config()
    # флаги берутся из админки (выключатель ИИ, подписка, Kaspi), а не из констант
    cfg.flags.ai_assistant = is_enabled(db, "ai_assistant")
    cfg.flags.kaspi_connection = kaspi_enabled(db)
    cfg.flags.analytics = settings.analytics_enabled and is_enabled(db, "analytics")  # 3.9
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


def _email_login_allowed(email: str) -> bool:
    """К-28 (решение владельца 27.11): в продакшене вход по коду из почты выключен для всех, кроме адреса владельца
    (SATTI_ADMIN_EMAIL) — так владелец открывает веб-админку; дальше обязательна 2FA."""
    return settings.email_login_enabled or (bool(settings.admin_email) and email == settings.admin_email)


@api.post("/auth/email/start", status_code=202, tags=["вход"])
def auth_email_start(body: EmailIn, request: Request, db: DbSession = Depends(get_session)) -> dict:
    email = _norm_email(body.email)
    if not _email_login_allowed(email):
        # тот же ответ, что при отправке: по ответу нельзя узнать адрес владельца
        return {"status": "sent", "expires_in": settings.code_ttl_minutes * 60}
    ip = client_ip(request)
    if not allow(f"code:{email}", settings.code_requests_per_hour, db=db) or not allow(f"codeip:{ip}", 20, db=db):
        raise ApiError(429, "rate_limited", "Слишком много попыток, подождите 10 минут.")
    code = new_code()
    db.add(AuthCode(email=email, purpose="login", code_hash=hash_code(email, code),
                    expires_at=utcnow() + timedelta(minutes=settings.code_ttl_minutes)))
    db.commit()
    try:
        send_code_email(email, code, "login", pick_lang(request.headers.get("accept-language")))
    except MailError as exc:
        raise ApiError(503, "mail_unavailable", "Не удалось отправить код. Попробуйте позже.") from exc
    return {"status": "sent", "expires_in": settings.code_ttl_minutes * 60}


@api.post("/auth/email/verify", tags=["вход"])
def auth_email_verify(body: VerifyIn, db: DbSession = Depends(get_session)) -> dict:
    email = _norm_email(body.email)
    if not _email_login_allowed(email):
        raise ApiError(400, "code_invalid")
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
        # аудит 27.11, L8: атомарно — параллельные запросы не обходят предел попыток
        db.execute(update(AuthCode).where(AuthCode.id == code_row.id).values(attempts=AuthCode.attempts + 1))
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
    analytics_service.record_safe("auth_method_used", _now())  # 3.9: только счётчик за день, после commit
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
    # 1.16: лимиты ведутся в сессии запроса (db=...) — второе соединение не открывается, пул не исчерпывается
    db.commit()
    if inst is None:
        # AUD-05: новая демо-установка создаёт магазин с данными — ограничиваем такие создания
        if not allow(f"demo:{client_ip(request)}", settings.demo_new_per_ip_per_hour, db=db):
            raise ApiError(429, "rate_limited", "Слишком много новых демо-сессий с этого адреса. Попробуйте позже.")
        total = db.scalar(select(func.count()).select_from(DemoInstallation)) or 0
        db.commit()
        if total >= settings.demo_max_installations:
            raise ApiError(503, "demo_full", "Демо-режим временно недоступен. Попробуйте позже.")
        _check_device_demo_limit(install_id, db)
        shop = create_demo_from_template(db, today_in(settings.default_timezone))
        inst = DemoInstallation(id=install_id, shop_id=shop.id, created_at=utcnow())
        db.add(inst)
    else:
        inst.last_active_at = utcnow()
        shop_missing = db.get(Shop, inst.shop_id) is None
        db.commit()
        if shop_missing:
            _check_device_demo_limit(install_id, db)
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
        _check_device_demo_limit(principal.demo_install_id, db)  # сброс тоже считается в лимит 3 в сутки
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


def _check_device_demo_limit(install_id: str, db: DbSession | None = None) -> None:
    """ADR-0005: не больше demo_per_device_per_day новых демо и сбросов в сутки с одного устройства.
    Счётчик в памяти процесса; при нескольких процессах его заменит общее хранилище лимитов (этап 1.15)."""
    if not allow(f"demo-dev:{install_id}", settings.demo_per_device_per_day, window=86400, db=db):
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
    locale: Literal["ru"] | None = None  # К-13: только русский


@api.get("/me", tags=["пользователь"], response_model=MeOut)
def me(principal: Principal = Depends(get_principal), db: DbSession = Depends(get_session)) -> dict:
    if principal.user_id is None:
        return {"demo": True, "email": None, "name": None, "locale": "ru"}
    user = current_user(principal, db)
    return {"demo": False, "id": user.id, "email": user.email, "name": user.name, "locale": user.locale,
            "age_confirmed": user.age_confirmed_at is not None,
            "terms_consent_required": user.terms_version != settings.legal_version,
            "seller_number": (n.number if (n := seller_access.by_user(db, user.id)) else None),
            "deactivated": user.deactivated_at is not None,
            "onboarding_done": user.onboarding_done_at is not None,
            "delete_on": (accounts_service._aware(user.delete_after).isoformat() if user.delete_after else None)}


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
def deletion_start(principal: Principal = Depends(get_principal), db: DbSession = Depends(get_session),
                   accept_language: str | None = Header(default=None)) -> dict:
    user = current_user(principal, db)
    if not allow(f"delstart:{user.id}", 5, db=db):  # аудит 27.11, M2: письма с кодом не бесконечно
        raise ApiError(429, "rate_limited", "Слишком много запросов кода. Попробуйте через час.")
    code = new_code()
    db.add(AuthCode(email=user.email, purpose="delete", user_id=user.id, code_hash=hash_code(user.email, code),
                    expires_at=utcnow() + timedelta(minutes=settings.code_ttl_minutes)))
    db.commit()
    try:
        send_code_email(user.email, code, "delete", pick_lang(accept_language))
    except MailError as exc:
        raise ApiError(503, "mail_unavailable", "Не удалось отправить код. Попробуйте позже.") from exc
    return {"status": "sent"}


class TermsIn(BaseModel):
    accepted: bool


class ConfirmIn(BaseModel):
    code: str = Field(min_length=6, max_length=6)


@api.post("/me/deletion/confirm", tags=["пользователь"])
def deletion_confirm(body: ConfirmIn, principal: Principal = Depends(get_principal),
                     db: DbSession = Depends(get_session)) -> dict:

    user = current_user(principal, db)
    if not accounts_service.check_delete_code(db, user, body.code):  # аудит 27.11, M2: попытки ограничены
        raise ApiError(400, "code_invalid")
    delete_user_account(db, user)  # AUD-08: все записи аккаунта, одна реализация для приложения и веба
    return {"status": "deleted"}


@api.post("/me/onboarding/complete", tags=["пользователь"])
def onboarding_complete(principal: Principal = Depends(get_principal), db: DbSession = Depends(get_session)) -> dict:
    """Обучение пройдено до конца (часть 2, п.6). Повторное прохождение из профиля отметку не снимает."""
    user = current_user(principal, db)
    if user.onboarding_done_at is None:
        user.onboarding_done_at = _now()
        db.commit()
    return {"onboarding_done": True}


@api.post("/me/deactivation/confirm", tags=["пользователь"])
def deactivation_confirm(body: ConfirmIn, principal: Principal = Depends(get_principal),
                         db: DbSession = Depends(get_session)) -> dict:
    """К-21: «Деактивировать на 30 дней» — тот же код из письма, что и для удаления (/me/deletion/start)."""

    user = current_user(principal, db)
    if not accounts_service.check_delete_code(db, user, body.code):  # аудит 27.11, M2: попытки ограничены
        raise ApiError(400, "code_invalid")
    delete_on = accounts_service.deactivate_user(db, user, _now())
    return {"status": "deactivated", "delete_on": delete_on.isoformat()}


def _paid_access(db: DbSession, shop: Shop) -> bool:
    """Оплаченная подписка с доступом сейчас: не пробный период и не доступ без подписки от владельца."""
    sub = get_subscription(db, shop.id)
    return sub is not None and sub.state == "active" and billing.has_access(sub, _now())


@api.post("/me/reactivation", tags=["пользователь"])
def reactivation(principal: Principal = Depends(get_principal), db: DbSession = Depends(get_session)) -> dict:
    """К-21: восстановление до конца 30 дней — только при оплаченной подписке 9 900 ₸ (проверена сервером у магазина).
    Подписка в App Store или Google Play сама не отменяется: если она ещё оплачена, восстановление сразу."""
    user = current_user(principal, db)
    if not accounts_service.is_deactivated(user):
        return {"status": "active"}
    shops = db.scalars(select(Shop).where(Shop.owner_user_id == user.id)).all()
    if not any(_paid_access(db, shop) for shop in shops):
        raise ApiError(402, "subscription_required",
                       "Восстановить аккаунт можно только с оплаченной подпиской. Оформите подписку.")
    accounts_service.reactivate_user(db, user)
    return {"status": "active"}


# ---------- магазины ----------

class ShopIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    timezone: str = settings.default_timezone
    language: Literal["ru"] = "ru"  # К-13: только русский


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
    # К-25 п.2 (решение владельца 23.11, 01:53): один аккаунт — один магазин. Демо-магазин устроен отдельно.
    if db.scalar(select(Shop.id).where(Shop.owner_user_id == user.id, Shop.is_demo.is_(False))) is not None:
        raise ApiError(409, "shop_exists", "В аккаунте уже есть магазин. Один аккаунт — один магазин Kaspi.")
    shop = Shop(owner_user_id=user.id, name=body.name, timezone=body.timezone, language=body.language)
    db.add(shop)
    db.commit()
    return _shop_json(shop)


class ShopPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    timezone: str | None = None
    language: Literal["ru"] | None = None  # К-13: только русский
    vat_payer: bool | None = None  # К-33 А2: «Я плательщик НДС»


@api.patch("/shops/{shop_id}", tags=["магазины"])
def shops_patch(shop_id: str, body: ShopPatch, principal: Principal = Depends(get_principal),
                db: DbSession = Depends(get_session)) -> dict:
    shop = shop_for(db, principal, shop_id)
    changes = body.model_dump(exclude_none=True)
    # К-33 А3: в демо и на встрече продавец пробует «плательщик НДС» — это можно; остальное в демо менять нельзя
    if shop.is_demo and set(changes) - {"vat_payer"}:
        raise ApiError(403, "forbidden")
    for k, v in changes.items():
        setattr(shop, k, v)
    db.commit()
    reportcache.invalidate(shop.id)  # AUD-12: данные отчётов изменились
    return _shop_json(shop)


def _shop_json(shop: Shop) -> dict:
    return {"id": shop.id, "name": shop.name, "timezone": shop.timezone, "language": shop.language,
            "is_demo": shop.is_demo, "vat_payer": bool(shop.vat_payer),
            "presentation_mode": bool(shop.presentation_mode),
            "example_cost_pct": shop.example_cost_pct if shop.presentation_mode else None}


# ---------- отчёты ----------

@api.get("/shops/{shop_id}/overview", tags=["обзор"], response_model=OverviewOut)
def get_overview(shop_id: str, period: str = Query("7d"), principal: Principal = Depends(get_principal),
                 db: DbSession = Depends(get_session)) -> dict:
    shop = shop_for(db, principal, shop_id)

    def compute() -> dict:
        data, facts = base_for(db, shop)
        return overview(data, facts, _period(period, shop), _now())

    out = dict(reportcache.memo(shop.id, f"overview|{period}|{_minute()}", compute))
    out["history_note"] = _history_note(db, shop, out.get("period", {}).get("from"))
    out["data_from"] = _kaspi_data_from(db, shop)  # К-18.4: с какой даты есть данные Kaspi
    unconfigured = reportcache.memo(shop.id, f"missing|{_minute()}", lambda: {"items": _unconfigured(db, shop)})
    out["attention"] = {**out["attention"], "not_configured_count": len(unconfigured["items"])}
    return out


def _kaspi_data_from(db: DbSession, shop: Shop) -> str | None:
    conn = db.get(KaspiConnection, shop.id)
    if conn is None:
        return None
    from datetime import timedelta as _td
    return (conn.connected_at.date() - _td(days=kaspi_service.FIRST_SYNC_DAYS)).isoformat()


def _history_note(db: DbSession, shop: Shop, period_from: str | None) -> str | None:
    """К-17.3: заказы Kaspi загружаются за последние 90 дней. Период раньше этого — цифры неполные, и это говорим прямо."""
    conn = db.get(KaspiConnection, shop.id)
    if conn is None or not period_from:
        return None
    from datetime import timedelta as _td
    earliest = (conn.connected_at.date() - _td(days=kaspi_service.FIRST_SYNC_DAYS)).isoformat()
    if period_from < earliest:
        return (f"Заказы Kaspi загружены не раньше {earliest[8:]}.{earliest[5:7]}.{earliest[:4]}. "
                "За более ранний период заказов в приложении нет, поэтому выручка и прибыль за него неполные.")
    return None


@api.get("/shops/{shop_id}/profit-breakdown", tags=["обзор"], response_model=ProfitBreakdownOut)
def get_profit_breakdown(shop_id: str, period: str = Query("7d"), principal: Principal = Depends(get_principal),
                         db: DbSession = Depends(get_session)) -> dict:
    shop = shop_for(db, principal, shop_id)

    def compute() -> dict:
        data, facts = base_for(db, shop)
        return profit_breakdown(data, facts, _period(period, shop))

    return reportcache.memo(shop.id, f"profit|{period}|{_minute()}", compute)


@api.get("/shops/{shop_id}/money", tags=["обзор"])
def get_money_insights(shop_id: str, principal: Principal = Depends(get_principal),
                       db: DbSession = Depends(get_session)) -> dict:
    """К-33 А5: главный экран языком денег — утечки маржи, минимальная цена без убытка, пороги доставки,
    защита от отмен. За последние 30 дней."""
    from .insights import money_insights

    shop = shop_for(db, principal, shop_id)

    def compute() -> dict:
        data, facts = base_for(db, shop)
        return money_insights(db, data, facts, _now())

    return reportcache.memo(shop.id, f"money|{_minute()}", compute)


@api.get("/shops/{shop_id}/orders", tags=["заказы"], response_model=OrdersPageOut)
def get_orders(shop_id: str, period: str = Query("7d"), status: str | None = None, q: str | None = None,
               cursor: str | None = None, limit: int = 50, principal: Principal = Depends(get_principal),
               db: DbSession = Depends(get_session)) -> dict:
    shop = shop_for(db, principal, shop_id)

    def compute() -> dict:
        data, _facts = base_for(db, shop)
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
    data, facts = base_for(db, shop)
    return order_detail(data, facts, order)


@api.get("/shops/{shop_id}/products/missing-costs", tags=["товары"], response_model=MissingCostsOut)
def get_missing_costs(shop_id: str, principal: Principal = Depends(get_principal),
                      db: DbSession = Depends(get_session)) -> dict:
    shop = shop_for(db, principal, shop_id)
    return reportcache.memo(shop.id, f"missing|{_minute()}", lambda: {"items": _unconfigured(db, shop)})


def _stocked_ids(db: DbSession, shop: Shop) -> set[str]:
    from .models import StockMovement

    ids = set(db.scalars(select(ProductStock.product_id).where(ProductStock.shop_id == shop.id)).all())
    ids |= set(db.scalars(select(StockMovement.product_id).where(StockMovement.shop_id == shop.id,
                                                                StockMovement.kind == "inventory")).all())
    return ids


def _unconfigured(db: DbSession, shop: Shop) -> list[dict]:
    """К-24: товары без себестоимости или без остатка. Пока не заполнены оба поля, товар «не настроен»."""
    data = base_for(db, shop)[0]
    no_cost = {row["product_id"] for row in missing_costs_list(data)}
    stocked = _stocked_ids(db, shop)
    hints = kaspi_service.catalog_stock_hints(db, shop.id)
    out = []
    for p in sorted(data.products.values(), key=lambda p: p.sku):
        needs_cost, needs_stock = p.id in no_cost, p.id not in stocked
        if needs_cost or needs_stock:
            out.append({"product_id": p.id, "sku": p.sku, "name": p.name, "category": p.category,
                        "needs_cost": needs_cost, "needs_stock": needs_stock, "stock_hint": hints.get(p.sku)})
    return out


def _record_inventory(db: DbSession, shop: Shop, product_id: str, qty: int) -> ProductStock:
    """Остаток на сейчас — событие «инвентаризация» (К-1). Продажи из истории до этого момента его не уменьшают."""
    from .models import StockMovement

    now = datetime.now(timezone.utc)
    presentation_service.drop_product_examples(db, shop.id, product_id, stock=True)  # К-33 А3
    row = db.scalar(select(ProductStock).where(ProductStock.product_id == product_id))
    if row is None:
        row = ProductStock(shop_id=shop.id, product_id=product_id, qty=qty, updated_at=now)
        db.add(row)
    else:
        row.qty, row.updated_at, row.last_alert_level = qty, now, None
    db.add(StockMovement(shop_id=shop.id, product_id=product_id, kind="inventory", qty=qty,
                         occurred_at=now, created_at=now))
    return row


@api.get("/shops/{shop_id}/products", tags=["товары"], response_model=ProductsPageOut)
def get_products(shop_id: str, period: str = Query("30d"), filter: str | None = Query(None, alias="filter"),
                 sort: str = "profit_asc", q: str | None = None, cursor: str | None = None, limit: int = 50,
                 principal: Principal = Depends(get_principal), db: DbSession = Depends(get_session)) -> dict:
    shop = shop_for(db, principal, shop_id)

    def compute() -> dict:
        data, facts = base_for(db, shop)
        return products_list(data, facts, _period(period, shop), filter, sort, q,
                             _cursor(cursor), _limit(limit))

    key = f"products|{period}|{filter}|{sort}|{q}|{cursor}|{limit}|{_minute()}"
    return reportcache.memo(shop.id, key, compute)


# ---------- подписка (ТЗ 2.1, раздел 8) ----------

@api.get("/shops/{shop_id}/subscription", tags=["подписка"], response_model=SubscriptionOut)
def get_subscription_state(shop_id: str, principal: Principal = Depends(get_principal),
                           db: DbSession = Depends(get_session)) -> dict:
    shop = shop_for(db, principal, shop_id, guard_access=False, allow_deactivated=True)
    body = subscription_view(db, shop)
    # Предварительно, без проверки телефона: Kaspi подключён, отметок аккаунта и магазина нет (К-21).
    # Окончательно — POST /subscription/offer с токеном проверки телефона.
    ok, _ = trial_decision(db, shop, _account_key(db, principal), DeviceVerdict(available=True, trial_used=False))
    body["trial_available"] = ok
    return body


class DeviceIn(BaseModel):
    """Одноразовый токен проверки телефона: DeviceCheck (iOS) или Play Integrity (Android). Не сохраняется."""
    platform: Literal["ios", "android"] | None = None
    device_token: str | None = Field(default=None, max_length=8192)


class OfferOut(BaseModel):
    trial_available: bool
    reason: str
    reason_text: str | None
    account_token: str  # appAccountToken (Apple) и obfuscatedAccountId (Google) для покупки
    apple_product_id: str
    google_subscription_id: str
    google_offer_id: str | None  # None — предложение с пробным периодом не показывать
    price_text: str
    trial_days: int


@api.post("/shops/{shop_id}/subscription/offer", tags=["подписка"], response_model=OfferOut)
def post_subscription_offer(body: DeviceIn, shop_id: str, principal: Principal = Depends(get_principal),
                            db: DbSession = Depends(get_session)) -> dict:
    """Что предлагать к покупке (К-21): подписка с пробным периодом или без него — по правилам Satti."""
    shop = shop_for(db, principal, shop_id, guard_access=False, allow_deactivated=True)
    if shop.is_demo:
        raise ApiError(409, "demo_purchase", "В демо-режиме подписку оформить нельзя. Войдите в аккаунт.")
    verdict = device_trust.check(db, body.platform, body.device_token)
    ok, reason = trial_decision(db, shop, _account_key(db, principal), verdict)
    return {"trial_available": ok, "reason": reason,
            "reason_text": None if ok else billing.TRIAL_REASON_TEXT.get(reason),
            "account_token": store_billing.account_token(shop.id),
            "apple_product_id": settings.apple_product_trial if ok else settings.apple_product_plain,
            "google_subscription_id": settings.google_subscription_id,
            "google_offer_id": settings.google_trial_offer_id if ok else None,
            "price_text": settings.subscription_price_text, "trial_days": billing.TRIAL_DAYS}


def _account_key(db: DbSession, principal: Principal) -> str | None:
    """Ключ аккаунта для защиты пробного периода: нормализованный email."""
    if principal.user_id is None:
        return None
    return current_user(principal, db).email.strip().lower()


@api.post("/shops/{shop_id}/subscription/trial", status_code=201, tags=["подписка"], response_model=SubscriptionOut)
def post_start_trial(shop_id: str, body: DeviceIn | None = None, principal: Principal = Depends(get_principal),
                     db: DbSession = Depends(get_session)) -> dict:
    """Пробный период без магазина приложений — только SATTI_BILLING_TEST_MODE. В боевом режиме его даёт
    App Store или Google Play (вводное предложение), а сервер видит его при проверке покупки."""
    shop = shop_for(db, principal, shop_id, guard_access=False)
    if not settings.billing_test_mode:
        raise ApiError(501, "store_not_configured", "Оформление через App Store и Google Play ещё не подключено.")
    body = body or DeviceIn()
    verdict = device_trust.check(db, body.platform, body.device_token)
    start_trial(db, shop, _account_key(db, principal), verdict, body.platform, body.device_token)
    return subscription_view(db, shop)


class PurchaseVerifyIn(DeviceIn):
    store: Literal["apple", "google"]
    # Apple — transactionId из StoreKit 2; Google — purchaseToken
    purchase_id: str = Field(min_length=1, max_length=1024)


def _trial_allowed(db: DbSession, shop, principal: Principal, platform: str | None, token: str | None) -> bool:
    """Пробный период уже идёт (выдан раньше) — оставляем; иначе — решение по правилам Satti (К-21)."""
    sub = get_subscription(db, shop.id)
    if sub is not None and sub.trial_started_at is not None and sub.state == "trial":
        return True
    ok, reason = trial_decision(db, shop, _account_key(db, principal), device_trust.check(db, platform, token))
    if not ok:
        log.info("store trial refused: %s", reason)
    return ok


@api.post("/shops/{shop_id}/subscription/verify", tags=["подписка"], response_model=SubscriptionOut)
def post_verify_purchase(body: PurchaseVerifyIn, shop_id: str, principal: Principal = Depends(get_principal),
                         db: DbSession = Depends(get_session)) -> dict:
    """Проверка покупки у магазина (App Store Server API, Google Play Developer API) и доступ по её состоянию.
    Тот же вызов — для «Восстановить покупки»: приложение присылает каждую найденную покупку.
    Деактивированный аккаунт (К-21) восстанавливается здесь же — только оплаченной подпиской, не пробным периодом."""
    shop = shop_for(db, principal, shop_id, guard_access=False, allow_deactivated=True)
    if shop.is_demo:
        raise ApiError(409, "demo_purchase", "В демо-режиме подписку оформить нельзя. Войдите в аккаунт.")
    owner = current_user(principal, db)
    deactivated = accounts_service.is_deactivated(owner)
    st = store_billing.fetch_state(body.store, body.purchase_id)
    allowed = True
    if st.in_trial and st.state == "trial":
        # деактивированному пробный период не даёт доступа: восстановление — только с оплатой (решение владельца 01:17)
        allowed = False if deactivated else _trial_allowed(db, shop, principal, body.platform, body.device_token)
    sub_before = get_subscription(db, shop.id)
    if allowed and st.in_trial and st.state == "trial" and (sub_before is None or sub_before.trial_started_at is None):
        # отметки ставятся до выдачи доступа: параллельный запрос упрётся в уникальное ограничение (AUD-16)
        billing.mark_trial_used(db, shop, _account_key(db, principal), body.platform, body.device_token)
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            allowed = False
    before_state = sub_before.state if sub_before is not None else None
    store_billing.bind_purchase(db, shop, st)
    store_billing.apply_state(db, shop, st, trial_allowed=allowed)
    after = get_subscription(db, shop.id)
    event = None
    if after is not None and after.state != before_state:  # 3.9: счётчики без персональных данных
        event = {"trial": "trial_started", "active": "subscription_started"}.get(after.state)
    db.add(AuditEvent(action="subscription_verify", entity=f"{st.store}:{st.state}", actor_id=principal.user_id,
                      shop_id=shop.id))
    db.commit()
    if event:
        analytics_service.record_safe(event, _now())  # после commit: отдельная сессия не ждёт блокировку
    if deactivated and _paid_access(db, shop):
        accounts_service.reactivate_user(db, owner)
    if st.store == "google" and st.needs_ack:
        store_billing.google_acknowledge(st.purchase_key)
    return subscription_view(db, shop)


def _apply_store_event(db: DbSession, store: str, event_id: str, kind: str, key: str | None) -> str:
    """Общая обработка уведомления: идемпотентно, состояние берётся у магазина, а не из уведомления."""
    if not event_id:
        raise ApiError(422, "validation", "Нет идентификатора уведомления.")
    if db.scalar(select(store_billing.StoreNotification.id).where(
            store_billing.StoreNotification.store == store,
            store_billing.StoreNotification.event_id == event_id)) is not None:
        return "duplicate"
    result = "ignored"
    event = None
    if key:
        st = store_billing.fetch_state(store, key)
        shop_id = store_billing.shop_for_state(db, st)
        shop = db.get(Shop, shop_id) if shop_id else None
        if shop is None:
            result = "unknown_purchase"  # приложение ещё не прислало покупку; привяжется при /verify
        else:
            store_billing.bind_purchase(db, shop, st)
            sub = get_subscription(db, shop.id)
            allowed = sub is not None and sub.trial_started_at is not None and sub.state == "trial"
            prev = sub.state if sub is not None else None
            store_billing.apply_state(db, shop, st, trial_allowed=allowed or not st.in_trial)
            now_state = get_subscription(db, shop.id).state if get_subscription(db, shop.id) else None
            if now_state == "active" and prev in ("active", "trial", "grace"):
                event = "subscription_renewed"  # 3.9
            elif now_state in ("expired", "revoked", "on_hold") and prev != now_state:
                event = "subscription_expired"
            if st.store == "google" and st.needs_ack:
                store_billing.google_acknowledge(st.purchase_key)
            result = st.state
    if not store_billing.record_notification(db, store, event_id, kind, result):
        db.rollback()
        return "duplicate"
    db.commit()
    if event:
        analytics_service.record_safe(event, _now())
    return result


class AppleNotificationIn(BaseModel):
    signedPayload: str = Field(min_length=10, max_length=100_000)


@api.post("/store/apple/notifications", tags=["подписка"], include_in_schema=False)
def apple_notifications(body: AppleNotificationIn, db: DbSession = Depends(get_session)) -> dict:
    """App Store Server Notifications V2: продление, отмена, возврат, льготный период (MASTER_PLAN 3.2)."""
    event_id, kind, key = store_billing.apple_notification_key(body.signedPayload)
    return {"result": _apply_store_event(db, "apple", event_id, kind, key)}


@api.post("/store/google/rtdn", tags=["подписка"], include_in_schema=False)
def google_rtdn(envelope: dict, token: str = Query(""), db: DbSession = Depends(get_session)) -> dict:
    """Google Real-time developer notifications через push-подписку Pub/Sub (MASTER_PLAN 3.2)."""
    if not settings.google_rtdn_token or not hmac.compare_digest(token, settings.google_rtdn_token):
        raise ApiError(403, "forbidden", "Неверный ключ уведомления.")
    event_id, kind, key = store_billing.google_notification_key(envelope)
    return {"result": _apply_store_event(db, "google", event_id, kind, key)}


XLSX_MEDIA = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@api.get("/shops/{shop_id}/exports/profit.xlsx", tags=["выгрузки"])
def export_profit_xlsx(shop_id: str, period: str = Query("30d"), principal: Principal = Depends(get_principal),
                       db: DbSession = Depends(get_session)) -> Response:
    """Отчёт о прибыли в Excel (ТЗ 2.1, 9.5). Итоги совпадают с экраном: те же функции расчёта."""
    shop = shop_for(db, principal, shop_id)
    data, facts = base_for(db, shop)
    p = _period(period, shop)
    content = profit_workbook(data, facts, p, _now())
    analytics_service.record_safe("excel_exported", _now())  # 3.9
    return Response(content=content, media_type=XLSX_MEDIA,
                    headers={"Content-Disposition": f'attachment; filename="{profit_filename(p)}"'})


@api.get("/me/export", tags=["пользователь"])
def export_my_data(principal: Principal = Depends(get_principal), db: DbSession = Depends(get_session)) -> Response:
    """«Скачать мои данные» (ТЗ 2.1, 9.4). Файл строится сразу и не хранится на сервере. До 3 выгрузок в сутки."""
    if principal.user_id is None:
        raise ApiError(403, "account_required", "Выгрузка доступна после входа по почте или через Apple/Google.")
    user = current_user(principal, db)
    if accounts_service.is_deactivated(user):
        raise ApiError(403, "account_deactivated", "Аккаунт деактивирован: данные недоступны до восстановления.")
    if not allow(f"export:{user.id}", 3, 86_400, db=db):
        raise ApiError(429, "rate_limited", "Выгрузок слишком много. Попробуйте завтра.")
    analytics_service.record_safe("data_export_requested", _now())  # 3.9
    content = user_export_zip(db, user)
    audit.record(db, "user_export", "user", actor_id=user.id)
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
    data, facts = base_for(db, shop)
    out = product_detail(data, facts, product, _period(period, shop), _now())
    # К-16.2: нет ставки комиссии для категории товара — пометка в карточке
    from .models import CommissionPreset
    has_rate = db.scalar(select(CommissionPreset.id).where(
        CommissionPreset.shop_id == shop.id, CommissionPreset.category == product.category).limit(1)) is not None
    out["commission_note"] = None if has_rate else "уточнить комиссию: для категории «" + product.category + "» нет ставки"
    return out


# ---------- затраты ----------

class CostIn(BaseModel):
    purchase: str  # сумма в тенге строкой, например "2800" или "2800.50"
    delivery_to_warehouse: str = "0"
    packaging: str = "0"
    other: str = "0"
    apply_to_history: bool | None = None  # None — по правилам раздела 7.5
    effective_from: date | None = None
    # К-24: остаток на сейчас вместе с себестоимостью — запись «инвентаризация» в журнале склада
    stock_qty: int | None = Field(default=None, ge=0, le=10_000_000)


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
    presentation_service.drop_product_examples(db, shop.id, product.id, cost=True)  # К-33 А3: свои цифры главнее
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


class StockIn(BaseModel):
    qty: int = Field(ge=0, le=10_000_000)  # остаток, внесённый продавцом вручную (склад)


class ReceiptIn(BaseModel):
    qty: int = Field(ge=1, le=10_000_000)  # приход: сколько штук поступило
    occurred_at: datetime | None = None  # дата прихода (событие), по умолчанию сейчас


class DelistIn(BaseModel):
    confirm: bool  # снять с продажи через XML — только после явного подтверждения


def _product_of_shop(db: DbSession, shop: Shop, product_id: str) -> Product:
    product = db.get(Product, product_id)
    if product is None or product.shop_id != shop.id:
        raise ApiError(404, "not_found")
    return product


def _stock_json(st, example: set[str] | None = None) -> dict:
    return {"example": bool(example and st.product_id in example),  # К-33 А3: остаток — пример
            "productId": st.product_id, "sku": st.sku, "name": st.name, "current": st.current, "baseQty": st.base_qty,
            "soldSince": st.sold_since, "returnedSince": st.returned_since, "avgDaily": st.avg_daily,
            "daysLeft": st.days_left, "level": st.level, "delisted": st.delisted,
            "pendingReturns": st.pending_returns,
            "returning": st.returning, "buffer": st.buffer, "forSale": st.for_sale}  # К-33 А4


@api.get("/shops/{shop_id}/products/{product_id}/stock", tags=["склад"])
def get_stock_row(shop_id: str, product_id: str, principal: Principal = Depends(get_principal),
                  db: DbSession = Depends(get_session)) -> dict:
    shop = shop_for(db, principal, shop_id)
    _product_of_shop(db, shop, product_id)
    st = stock_states(db, shop).get(product_id)
    if st is None:
        return {"qty": None, "updatedAt": None, "current": None, "level": None, "delisted": False}
    return {"qty": st.current, "updatedAt": st.base_at.isoformat(), **_stock_json(st)}


@api.get("/shops/{shop_id}/stock", tags=["склад"])
def list_stock(shop_id: str, principal: Principal = Depends(get_principal),
               db: DbSession = Depends(get_session)) -> dict:
    shop = shop_for(db, principal, shop_id)
    states = stock_states(db, shop)
    example, _cost = presentation_service.example_product_ids(db, shop.id)
    return {"items": [_stock_json(st, example) for st in sorted(states.values(), key=lambda x: x.name)]}


@api.get("/shops/{shop_id}/stock/delist-preview", tags=["склад"])
def stock_delist_preview(shop_id: str, principal: Principal = Depends(get_principal),
                         db: DbSession = Depends(get_session)) -> dict:
    """К-33 А3: предпросмотр автоснятия — «вот товары, которые сняли бы с продажи сейчас» (остаток 0 или снят вручную).
    Ничего не меняет ни у нас, ни в Kaspi."""
    shop = shop_for(db, principal, shop_id)
    states = stock_states(db, shop)
    example, _cost = presentation_service.example_product_ids(db, shop.id)
    items = [{**_stock_json(st, example), "reason": "delisted" if st.delisted else "out_of_stock"}
             for st in sorted(states.values(), key=lambda x: x.name) if st.delisted or st.for_sale <= 0]
    return {"items": items, "count": len(items), "presentation_mode": bool(shop.presentation_mode),
            "note": "Предпросмотр: в магазине Kaspi ничего не меняется."}


class ExampleCostIn(BaseModel):
    percent: int = Field(ge=presentation_service.MIN_COST_PCT, le=presentation_service.MAX_COST_PCT)


@api.post("/shops/{shop_id}/presentation/cost-percent", tags=["магазины"])
def presentation_cost_percent(shop_id: str, body: ExampleCostIn, principal: Principal = Depends(get_principal),
                              db: DbSession = Depends(get_session)) -> dict:
    """К-33 А3: себестоимость-пример «≈ N % от цены» — меняется прямо на встрече. Только в режиме презентации."""
    shop = shop_for(db, principal, shop_id)
    if not shop.presentation_mode:
        raise ApiError(409, "presentation_off", "Режим презентации не включён.")
    out = presentation_service.set_cost_pct(db, shop, body.percent, datetime.now(timezone.utc))
    db.commit()
    return out


@api.get("/shops/{shop_id}/stock/alerts", tags=["склад"])
def stock_alerts(shop_id: str, principal: Principal = Depends(get_principal),
                 db: DbSession = Depends(get_session)) -> dict:
    """Уведомления 10/5/3 шт. и 0 — в приложении (этот список) и push на моке (файл в outbox). Ниже порога — один раз."""
    shop = shop_for(db, principal, shop_id)
    states = stock_states(db, shop)
    rows = {r.product_id: r for r in db.scalars(select(ProductStock).where(ProductStock.shop_id == shop.id)).all()}
    example, _cost = presentation_service.example_product_ids(db, shop.id)
    items = []
    for st in states.values():
        row = rows.get(st.product_id)
        if st.level is None:
            if row is not None:
                row.last_alert_level = None  # выше порогов — можно снова уведомить при понижении
            continue
        items.append(_stock_json(st, example))
        if st.product_id in example:
            continue  # К-33 А3: пример остатка — без уведомлений
        if row is not None and row.last_alert_level != st.level:
            row.last_alert_level = st.level
            stock_push_mock(shop, st)
    db.commit()
    ending = [i for i in items if i["daysLeft"] is not None and 0 < i["daysLeft"] <= ENDING_SOON_DAYS]
    return {"items": items, "endingSoon": ending}


@api.put("/shops/{shop_id}/products/{product_id}/stock", tags=["склад"])
def put_stock_row(shop_id: str, product_id: str, body: StockIn, principal: Principal = Depends(get_principal),
                  db: DbSession = Depends(get_session)) -> dict:
    """Инвентаризация: остаток на сейчас (событие журнала). Продажи и возвраты после неё уменьшают и увеличивают остаток."""
    shop = shop_for(db, principal, shop_id)
    _product_of_shop(db, shop, product_id)
    row = _record_inventory(db, shop, product_id, body.qty)
    db.commit()
    reportcache.invalidate(shop.id)  # список «не настроенных» товаров изменился
    return {"qty": row.qty, "updatedAt": row.updated_at.isoformat()}


class ReturnConfirmIn(BaseModel):
    sellable: bool  # True — товар вернулся на склад и годен; False — не вернулся или брак


@api.post("/shops/{shop_id}/products/{product_id}/stock/returns", tags=["склад"])
def stock_confirm_returns(shop_id: str, product_id: str, body: ReturnConfirmIn,
                          principal: Principal = Depends(get_principal), db: DbSession = Depends(get_session)) -> dict:
    """К-26: возвраты Kaspi без отметки «вернулся на склад» — продавец подтверждает; годный товар увеличивает остаток."""
    from .models import OrderItem, ReturnEvent

    shop = shop_for(db, principal, shop_id)
    _product_of_shop(db, shop, product_id)
    item_ids = select(OrderItem.id).where(OrderItem.shop_id == shop.id, OrderItem.product_id == product_id)
    rows = db.scalars(select(ReturnEvent).where(ReturnEvent.shop_id == shop.id, ReturnEvent.goods_sellable.is_(None),
                                                ReturnEvent.item_id.in_(item_ids))).all()
    for r in rows:
        r.goods_sellable = body.sellable
    db.commit()
    reportcache.invalidate(shop.id)
    return {"confirmed": sum(r.returned_qty for r in rows), "sellable": body.sellable}


class PickedUpIn(BaseModel):
    qty: int = Field(ge=1, le=100_000)
    sellable: bool  # годен к продаже / брак


@api.post("/shops/{shop_id}/products/{product_id}/stock/picked-up", tags=["склад"])
def stock_picked_up(shop_id: str, product_id: str, body: PickedUpIn, principal: Principal = Depends(get_principal),
                    db: DbSession = Depends(get_session)) -> dict:
    """К-33 А4: отмена после передачи в Kaspi Доставку — продавец забрал товар в пункте приёма. Годный товар
    возвращается в остаток, брак — нет. Больше, чем едет обратно, подтвердить нельзя."""
    from .models import StockMovement
    shop = shop_for(db, principal, shop_id)
    _product_of_shop(db, shop, product_id)
    st = stock_states(db, shop).get(product_id)
    if st is None or st.returning <= 0:
        raise ApiError(409, "nothing_returning", "Этот товар не едет обратно.")
    if body.qty > st.returning:
        raise ApiError(422, "validation", f"Обратно едет только {st.returning} шт.")
    now = datetime.now(timezone.utc)
    db.add(StockMovement(shop_id=shop.id, product_id=product_id, kind="back_ok" if body.sellable else "back_defect",
                         qty=body.qty, occurred_at=now, created_at=now))
    db.commit()
    reportcache.invalidate(shop.id)
    after = stock_states(db, shop)[product_id]
    return {"current": after.current, "returning": after.returning}


class BufferIn(BaseModel):
    buffer: int = Field(ge=0, le=10_000)


@api.put("/shops/{shop_id}/products/{product_id}/stock/buffer", tags=["склад"])
def stock_buffer(shop_id: str, product_id: str, body: BufferIn, principal: Principal = Depends(get_principal),
                 db: DbSession = Depends(get_session)) -> dict:
    """К-33 А4: буфер автоснятия — сколько штук не показывать в Kaspi (по умолчанию 0). Товар снимается с продажи,
    когда остаток не больше буфера."""
    shop = shop_for(db, principal, shop_id)
    _product_of_shop(db, shop, product_id)
    row = db.scalar(select(ProductStock).where(ProductStock.product_id == product_id))
    if row is None:
        st0 = stock_states(db, shop).get(product_id)
        if st0 is None:
            raise ApiError(409, "stock_not_counted", "Сначала внесите остаток товара.")
        # остаток ведётся по журналу (например, пример в режиме презентации) — строка только для буфера
        row = ProductStock(shop_id=shop.id, product_id=product_id, qty=st0.current, updated_at=datetime.now(timezone.utc))
        db.add(row)
    row.buffer = body.buffer
    db.commit()
    st = stock_states(db, shop)[product_id]
    return {"buffer": st.buffer, "forSale": st.for_sale, "current": st.current}


@api.post("/shops/{shop_id}/products/{product_id}/stock/receipt", tags=["склад"])
def stock_receipt(shop_id: str, product_id: str, body: ReceiptIn, principal: Principal = Depends(get_principal),
                  db: DbSession = Depends(get_session)) -> dict:
    """Приход. Дата события — occurred_at (по умолчанию сейчас); приход учитывается, если он позже последней инвентаризации.
    Без инвентаризации остаток не ведётся: сначала пересчитайте товар."""
    from .models import StockMovement
    shop = shop_for(db, principal, shop_id)
    _product_of_shop(db, shop, product_id)
    now = datetime.now(timezone.utc)
    occurred = body.occurred_at or now
    if occurred.tzinfo is None:
        occurred = occurred.replace(tzinfo=timezone.utc)
    if occurred > now + timedelta(minutes=1):
        raise ApiError(422, "validation", "Дата прихода не может быть в будущем.")
    st = stock_states(db, shop).get(product_id)
    if st is None:
        raise ApiError(409, "stock_not_counted", "Сначала пересчитайте товар (инвентаризация), потом вносите приход.")
    db.add(StockMovement(shop_id=shop.id, product_id=product_id, kind="receipt", qty=body.qty,
                         occurred_at=occurred, created_at=now))
    db.commit()
    current = stock_states(db, shop)[product_id].current
    return {"qty": current, "current": current}


@api.post("/shops/{shop_id}/products/{product_id}/stock/delist", tags=["склад"])
def stock_delist(shop_id: str, product_id: str, body: DelistIn, principal: Principal = Depends(get_principal),
                 db: DbSession = Depends(get_session)) -> dict:
    """Снятие с продажи (XML-прайс): только при нулевом остатке и после подтверждения (confirm=true)."""
    shop = shop_for(db, principal, shop_id)
    _product_of_shop(db, shop, product_id)
    st = stock_states(db, shop).get(product_id)
    if st is None or st.current > 0:
        raise ApiError(409, "stock_not_empty", "Снять с продажи можно только товар с нулевым остатком.")
    if not body.confirm:
        raise ApiError(422, "confirm_required", "Подтвердите снятие с продажи.")
    row = db.scalar(select(ProductStock).where(ProductStock.product_id == product_id))
    row.delisted = True
    db.commit()
    return {"delisted": True}


@api.post("/shops/{shop_id}/products/{product_id}/stock/relist", tags=["склад"])
def stock_relist(shop_id: str, product_id: str, principal: Principal = Depends(get_principal),
                 db: DbSession = Depends(get_session)) -> dict:
    shop = shop_for(db, principal, shop_id)
    _product_of_shop(db, shop, product_id)
    row = db.scalar(select(ProductStock).where(ProductStock.product_id == product_id))
    if row is not None:
        row.delisted = False
        db.commit()
    return {"delisted": False}


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
        ProductCostVersion.cancelled.is_(False), ProductCostVersion.source != presentation_service.EXAMPLE,
        ProductCostVersion.created_at >= datetime.now(timezone.utc) - timedelta(seconds=60),
    ).order_by(ProductCostVersion.created_at.desc()).limit(1))
    if recent is not None and (recent.purchase_minor, recent.delivery_to_warehouse_minor,
                               recent.packaging_minor, recent.other_minor) == values \
            and (body.effective_from is None or recent.effective_from == body.effective_from):
        if body.stock_qty is not None:
            _record_inventory(db, shop, product.id, body.stock_qty)
            db.commit()
            reportcache.invalidate(shop.id)
        return _version_json(recent)
    v = _add_cost(db, shop, product, body, "manual")
    if body.stock_qty is not None:
        _record_inventory(db, shop, product.id, body.stock_qty)
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
    purchase: str | None = None  # None — себестоимость уже указана, вводится только остаток (К-24)
    stock_qty: int | None = Field(default=None, ge=0, le=10_000_000)
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
        if item.purchase is None and item.stock_qty is None:
            raise ApiError(422, "validation", "Укажите себестоимость или остаток.")
        if item.purchase is not None:
            _add_cost(db, shop, product, CostIn(**item.model_dump(exclude={"product_id", "stock_qty", "purchase"}),
                                                purchase=item.purchase,
                                                apply_to_history=body.apply_to_history), "manual")
        if item.stock_qty is not None:
            _record_inventory(db, shop, product.id, item.stock_qty)
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
    analytics_service.record_safe("tax_rate_saved", _now())  # 3.9
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
    if not allow(key, settings.import_requests_per_hour, db=db):
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

    batch.payload = json.dumps({**json.loads(batch.payload), "mapping": body.mapping,
                                "duplicates": body.duplicates}, ensure_ascii=False)
    batch.status = "previewed"
    db.commit()
    reportcache.invalidate(shop.id)  # AUD-12: данные отчётов изменились
    return {"status": "ok"}


def _preview_data(db: DbSession, shop: Shop, batch: ImportBatch) -> dict:

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
        presentation_service.drop_product_examples(db, shop.id, product.id, cost=True)  # К-33 А3
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
    if not active:  # К-24: согласие на ИИ — в галочке условий; старая версия условий — принять обновлённые
        raise ApiError(403, "terms_consent_required", "Примите обновлённые условия и политику конфиденциальности.")
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
    """Карточка товара (К-14, ADR 0011): живая модель с фото; при выключателе, бюджете или сбое модели — шаблон с пометкой."""
    shop = shop_for(db, principal, shop_id)  # проверка доступа к магазину
    _, active = ai_consent_state(db, principal)
    if not active:  # К-24: согласие на ИИ — в галочке условий; старая версия условий — принять обновлённые
        raise ApiError(403, "terms_consent_required", "Примите обновлённые условия и политику конфиденциальности.")
    if not facts.strip() or len(facts) > 1000:  # аудит 27.11, M3: до вызова модели, а не только в шаблоне
        raise ApiError(422, "validation", "Опишите товар: от 1 до 1000 символов.")
    if len(photos) > 5:
        raise ApiError(422, "validation", "Можно добавить не больше 5 фото.")
    photo_bytes: list[bytes] = []
    for ph in photos:
        data = await ph.read(draft_ai.MAX_PHOTO_BYTES + 1)  # аудит 27.11, L7: не читаем больше лимита
        if not (data.startswith(b"\xff\xd8\xff") or data.startswith(b"\x89PNG") or (data[:4] == b"RIFF" and data[8:12] == b"WEBP")):
            raise ApiError(422, "validation", "Фото должно быть в формате JPG, PNG или WebP.")
        if len(data) > draft_ai.MAX_PHOTO_BYTES:
            raise ApiError(422, "validation", "Фото больше 5 МБ. Уменьшите размер и попробуйте снова.")
        photo_bytes.append(data)
    # Фото не сохраняются на сервере: они живут только в памяти этого запроса.
    reason = None
    if not is_enabled(db, "ai_assistant"):
        reason = "помощник сейчас выключен"
    elif not (settings.ai_live and settings.anthropic_api_key):
        reason = "ИИ сейчас недоступен"
    reserved_id = None
    if reason is None:
        # квота и бюджет — как у помощника: ai_limit (429) показываем как есть, исчерпанный бюджет — шаблоном.
        # Аудит 27.11, M3: вызов резервируется под той же блокировкой, что и проверка квоты, — параллельные
        # запросы не проходят квоту все сразу. Реальная стоимость записывается после ответа модели.
        with quota_guard(principal.user_id or shop.id):
            try:
                ai_service.require_budget(db, _now())
                ai_service.check_quota(db, principal.user_id, shop.id, _now())
            except ApiError as exc:
                if exc.code != "ai_budget_exhausted":
                    raise
                reason = "бюджет ИИ на сегодня исчерпан"
            else:
                reserve = AIUsageEvent(user_id=principal.user_id, shop_id=shop.id, created_at=_now(), tool_calls=0,
                                       kind="draft", cost_micro_usd=settings.ai_cost_per_call_micro_usd)
                db.add(reserve)
                db.commit()
                reserved_id = reserve.id
    if reason is None:
        try:
            result = await run_in_threadpool(draft_ai.live_draft, facts, photo_bytes)
        except draft_ai.DraftFallback as exc:
            log.warning("product draft fallback: %s", exc)  # причина без текста фактов
            reason = "ИИ не смог составить проверяемый черновик"
            if reserved_id is not None:  # шаблон квоту не тратит — снимаем резерв
                db.execute(delete(AIUsageEvent).where(AIUsageEvent.id == reserved_id))
                db.commit()
        else:
            cost = ai_service.live_cost_micro(result.tin, result.tout, result.tcw, result.tcr)
            db.execute(update(AIUsageEvent).where(AIUsageEvent.id == reserved_id).values(cost_micro_usd=cost))
            db.commit()
            ai_service.check_budget_alerts(db, _now())
            return {**result.draft, "generatedBy": "ai", "languages": "ru", "photosUsed": result.photos_sent,
                    "warnings": ["Черновик ИИ — проверьте перед публикацией. Satti ничего не публикует в Kaspi."]}
    # шаблон: тот же текст, что без ИИ, с понятной пометкой о причине
    out = ai_service.product_draft(facts, "ru", len(photos))
    out["generatedBy"] = "template"
    out["warnings"] = [f"Составлено по шаблону: {reason}. Проверьте текст перед публикацией.", *out["warnings"]]
    return out


class ReplyDraftIn(BaseModel):
    question: str = Field(min_length=1, max_length=500)
    tone: Literal["polite", "short"] = "polite"


@api.post("/ai/reply-drafts", status_code=201, tags=["ИИ"])
def ai_reply_draft(body: ReplyDraftIn, shop_id: str = Query(...), principal: Principal = Depends(get_principal),
                   db: DbSession = Depends(get_session)) -> dict:
    """К-35 п.2: ответ покупателю — живой ИИ по сути вопроса; в дневном лимите ИИ. Лимит или бюджет исчерпан,
    ИИ недоступен или ответ не прошёл проверку — шаблон по теме вопроса с пометкой причины."""
    shop = shop_for(db, principal, shop_id)
    require_ai(db)  # выключатель ИИ (QA-02)
    _, active = ai_consent_state(db, principal)
    if not active:  # К-24: согласие на ИИ — в галочке условий; старая версия условий — принять обновлённые
        raise ApiError(403, "terms_consent_required", "Примите обновлённые условия и политику конфиденциальности.")
    base = ai_service.reply_draft(body.question, body.tone)  # проверка ввода (422 — квота не тратится), маскировка
    masked = base.pop("question_masked")
    reason = None
    reserved_id = None
    if not (settings.ai_live and settings.anthropic_api_key):
        reason = "ИИ сейчас недоступен"
    else:
        with quota_guard(principal.user_id or shop.id):
            try:
                ai_service.require_budget(db, _now())
                ai_service.check_quota(db, principal.user_id, shop.id, _now())
            except ApiError as exc:
                if exc.code == "ai_budget_exhausted":
                    reason = "бюджет ИИ на сегодня исчерпан"
                elif exc.code == "ai_limit":
                    reason = "дневной лимит ИИ исчерпан"
                else:
                    raise
            else:
                reserve = AIUsageEvent(user_id=principal.user_id, shop_id=shop.id, created_at=_now(), tool_calls=0,
                                       kind="draft", cost_micro_usd=settings.ai_cost_per_call_micro_usd)
                db.add(reserve)
                db.commit()
                reserved_id = reserve.id
    if reason is None:
        try:
            result = draft_ai.live_reply(masked, body.tone)
        except draft_ai.DraftFallback as exc:
            log.warning("reply draft fallback: %s", exc)  # причина без текста вопроса
            reason = "ответ ИИ не прошёл проверку"
            db.execute(delete(AIUsageEvent).where(AIUsageEvent.id == reserved_id))  # шаблон квоту не тратит
            db.commit()
        else:
            cost = ai_service.live_cost_micro(result.tin, result.tout, result.tcw, result.tcr)
            db.execute(update(AIUsageEvent).where(AIUsageEvent.id == reserved_id).values(cost_micro_usd=cost))
            db.commit()
            ai_service.check_budget_alerts(db, _now())
            return {"reply": result.draft["reply"], "warnings": ["Черновик ИИ — проверьте перед отправкой.",
                                                                 *base["warnings"]], "generatedBy": "ai"}
    return {"reply": base["reply"], "generatedBy": "template",
            "warnings": [f"Составлено по шаблону: {reason}. Проверьте и дополните перед отправкой.", *base["warnings"]]}


# ---------- уведомления и Kaspi (за флагом) ----------

class PushIn(BaseModel):
    token: str = Field(min_length=8, max_length=512)
    platform: Literal["ios", "android"]


@api.post("/devices/push-token", status_code=204, tags=["уведомления"])
def push_token(body: PushIn, principal: Principal = Depends(get_principal),
               db: DbSession = Depends(get_session)) -> Response:
    """3.4: Expo push token устройства — к аккаунту (демо уведомлений не получает). Повтор — обновление владельца."""
    from . import push as push_service

    user = current_user(principal, db)
    row = db.get(push_service.DeviceToken, body.token)
    if row is None:
        db.add(push_service.DeviceToken(token=body.token, user_id=user.id, platform=body.platform))
    else:
        row.user_id, row.platform = user.id, body.platform
    db.commit()
    return Response(status_code=204)


@api.delete("/devices/push-token", status_code=204, tags=["уведомления"])
def push_token_delete(body: PushIn, principal: Principal = Depends(get_principal),
                      db: DbSession = Depends(get_session)) -> Response:
    """Выход из аккаунта: телефон больше не получает уведомления этого аккаунта."""
    from . import push as push_service

    user = current_user(principal, db)
    row = db.get(push_service.DeviceToken, body.token)
    if row is not None and row.user_id == user.id:
        db.delete(row)
        db.commit()
    return Response(status_code=204)


@api.get("/notification-settings", tags=["уведомления"])
def notification_settings_get(principal: Principal = Depends(get_principal),
                              db: DbSession = Depends(get_session)) -> dict:
    """3.4: текущие настройки — экран показывает их, а не «всё выключено»."""
    user = current_user(principal, db)
    row = db.get(NotificationSettings, user.id)
    return {"product_in_minus": bool(row and row.product_in_minus), "weekly_summary": bool(row and row.weekly_summary),
            "quiet_hours": bool(row and row.quiet_hours)}


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


def kaspi_enabled(db: DbSession) -> bool:
    """2.6: нужны и KASPI_ENABLED на сервере (по умолчанию выключен), и флаг в админке. Так приложение и сервер согласованы."""
    return settings.kaspi_connection_enabled and is_enabled(db, "kaspi_connection")


def _require_kaspi(db: DbSession) -> None:
    if not kaspi_enabled(db):
        raise _kaspi_disabled()


class KaspiConnectIn(BaseModel):
    seller_id: str = Field(min_length=1, max_length=64)
    token: str = Field(min_length=8, max_length=256)


class KaspiStoresIn(BaseModel):
    store_ids: list[str] = Field(default_factory=list, max_length=20)


def _aware_dt(dt: datetime) -> datetime:
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _kaspi_view(shop: Shop, conn: KaspiConnection | None, db: DbSession | None = None) -> dict:
    if conn is None:
        return {"enabled": True, "status": "not_connected"}
    catalog = kaspi_service.get_catalog(db, shop.id) if db is not None else None
    # К-16.3: ссылку на прайс показываем только после импорта прайса продавца
    price_path = f"/v1/kaspi/price/{shop.id}/{conn.price_key}"
    price_url = None
    if catalog is not None:
        price_url = (settings.public_base_url + price_path) if settings.public_base_url else price_path
    return {"enabled": True, "status": conn.status, "seller_id": conn.seller_id,
            "connected_at": conn.connected_at.isoformat(),
            "last_sync_at": conn.last_sync_at.isoformat() if conn.last_sync_at else None,
            "last_error": conn.last_error,
            # К-21: окно восстановления токена, открытое владельцем в админке (24 часа)
            "reconnect_until": (conn.reconnect_until.isoformat()
                                if conn.reconnect_until is not None and _aware_dt(conn.reconnect_until) > utcnow() else None),
            "store_ids": kaspi_service.store_list(conn),
            "store_hint": conn.store_hint,
            "catalog": ({"offers_count": catalog.offers_count, "imported_at": catalog.imported_at.isoformat()}
                        if catalog is not None else None),
            # К-18.3: прогресс первой загрузки (этап 1 — 7 дней, затем догрузка 90 дней)
            "load": {"done": conn.load_done or 0, "total": conn.load_total, "complete": bool(conn.backfill_done)},
            "price_url": price_url,
            "price_hint": None if catalog is not None else (
                "Сначала загрузите прайс-лист из кабинета Kaspi (Товары → Выгрузка прайс-листа). "
                "Без него ссылку на прайс не показываем: иначе Kaspi может снять с продажи товары, которых нет в файле.")}


@api.post("/shops/{shop_id}/kaspi/connection", tags=["Kaspi"], status_code=201)
def kaspi_connect(shop_id: str, body: KaspiConnectIn, principal: Principal = Depends(get_principal),
                  db: DbSession = Depends(get_session)) -> dict:
    _require_kaspi(db)
    shop = shop_for(db, principal, shop_id, guard_access=False)  # подключение Kaspi — до пробного периода (К-21)
    now = utcnow()
    existing = db.get(KaspiConnection, shop.id)
    if existing is not None:
        # К-21 (решение владельца 01:31): токен подключается один раз; замена — только через поддержку
        window = existing.reconnect_until
        if window is None or (window if window.tzinfo else window.replace(tzinfo=timezone.utc)) <= now:
            raise ApiError(409, "kaspi_already_connected",
                           "Магазин Kaspi уже подключён. Сменить токен нельзя; если он перестал работать — "
                           "напишите в поддержку.")
        if body.seller_id.strip() != existing.seller_id:
            raise ApiError(409, "kaspi_other_shop", "Можно ввести только токен того же магазина Kaspi.")
    seller_access.check_can_connect(db, principal.user_id, body.seller_id)
    if principal.user_id and existing is None:
        owner = db.get(User, principal.user_id)
        if owner is not None and owner.onboarding_done_at is None:
            # решение владельца 02:19: без пройденного обучения подключение Kaspi недоступно
            raise ApiError(403, "onboarding_required", "Сначала пройдите обучение по приложению — это займёт несколько минут.")
    client = KaspiClient(body.token)
    analytics_service.record(db, "kaspi_connect_started", now)
    try:
        conn = kaspi_service.connect(db, shop, body.seller_id.strip(), body.token, client, now)
    except KaspiAuthError as exc:
        analytics_service.record(db, "kaspi_connect_failed", now)
        raise ApiError(422, "kaspi_token_rejected", "Kaspi не принял этот ключ. Проверьте ключ и ID продавца.") from exc
    except KaspiUnavailable as exc:
        analytics_service.record(db, "kaspi_connect_failed", now)
        raise ApiError(503, "kaspi_unavailable", "Kaspi сейчас недоступен. Попробуйте позже.") from exc
    finally:
        client.close()
    analytics_service.record(db, "kaspi_connect_succeeded", now)
    if not shop.is_demo:
        seller_access.bind(db, principal.user_id, shop.id, conn.seller_id)  # номер продавца — один раз (К-21)
        db.commit()
    audit.record(db, "kaspi_connect", "kaspi_connection", actor_id=principal.user_id, shop_id=shop.id)
    return _kaspi_view(shop, conn, db)


@api.post("/shops/{shop_id}/kaspi/pay-report", tags=["Kaspi"])
async def kaspi_pay_report(shop_id: str, file: UploadFile = File(...), principal: Principal = Depends(get_principal),
                           db: DbSession = Depends(get_session)) -> dict:
    """К-33 Б1: сверка с Kaspi — выгрузка Kaspi Pay «Продажи» (Excel) против расчёта Satti по каждому заказу:
    «совпало N; расхождение X ₸ по M заказам». Строки выгрузки сохраняются."""
    from . import kaspi_pay

    shop = shop_for(db, principal, shop_id)
    key = f"pay:{principal.user_id or principal.demo_install_id or principal.session_id}"
    if not allow(key, settings.import_requests_per_hour, db=db):
        raise ApiError(429, "rate_limited")
    content = await file.read(settings.import_max_bytes + 1)
    parsed = await run_in_threadpool(parse_file, file.filename or "file", content)
    pay = kaspi_pay.parse_pay(parsed)
    result = kaspi_pay.reconcile(db, shop, pay, _now())
    return result


@api.post("/shops/{shop_id}/kaspi/catalog", tags=["Kaspi"])
async def kaspi_upload_catalog(shop_id: str, file: UploadFile = File(...), principal: Principal = Depends(get_principal),
                               db: DbSession = Depends(get_session)) -> dict:
    """Импорт прайс-листа продавца из кабинета Kaspi (К-16.3). Наш файл потом строится из него."""
    _require_kaspi(db)
    shop = shop_for(db, principal, shop_id)
    conn = db.get(KaspiConnection, shop.id)
    if conn is None:
        raise ApiError(409, "kaspi_not_connected", "Сначала подключите Kaspi.")
    data = await file.read(kaspi_service.MAX_CATALOG_BYTES + 1)
    try:
        kaspi_service.import_catalog(db, shop.id, data, _now())
    except ValueError as exc:
        raise ApiError(422, "kaspi_catalog_invalid", str(exc)) from exc
    return _kaspi_view(shop, conn, db)


@api.put("/shops/{shop_id}/kaspi/stores", tags=["Kaspi"])
def kaspi_set_stores(shop_id: str, body: KaspiStoresIn, principal: Principal = Depends(get_principal),
                     db: DbSession = Depends(get_session)) -> dict:
    """Коды складов Kaspi (storeId) — без переподключения и без сброса курсора синхронизации."""
    _require_kaspi(db)
    shop = shop_for(db, principal, shop_id)
    try:
        kaspi_service.set_store_ids(db, shop.id, body.store_ids)
    except ValueError as exc:
        raise ApiError(422, "kaspi_store_invalid", str(exc)) from exc
    except KaspiUnavailable as exc:
        raise ApiError(409, "kaspi_not_connected", "Сначала подключите Kaspi.") from exc
    conn = db.get(KaspiConnection, shop.id)
    return _kaspi_view(shop, conn, db)


@api.get("/shops/{shop_id}/kaspi/connection", tags=["Kaspi"])
def kaspi_status(shop_id: str, principal: Principal = Depends(get_principal), db: DbSession = Depends(get_session)) -> dict:
    if not kaspi_enabled(db):
        return {"enabled": False, "status": "not_connected"}
    shop = shop_for(db, principal, shop_id)
    return _kaspi_view(shop, db.get(KaspiConnection, shop.id), db)


@api.post("/shops/{shop_id}/kaspi/sync", tags=["Kaspi"])
def kaspi_sync_now(shop_id: str, principal: Principal = Depends(get_principal), db: DbSession = Depends(get_session)) -> dict:
    _require_kaspi(db)
    shop = shop_for(db, principal, shop_id)
    conn = db.get(KaspiConnection, shop.id)
    if conn is None:
        raise ApiError(404, "not_found", "Магазин Kaspi не подключён.")
    db.commit()  # соединение — лимиту ниже (см. demo_session)
    if not allow(f"kaspi-sync:{shop.id}", 12, 3600, db=db):
        raise ApiError(429, "rate_limited", "Слишком часто. Синхронизация доступна не чаще 12 раз в час.")
    # К-17.3: первая загрузка большого магазина (тысячи заказов) идёт часы — в фоне планировщика, а не в запросе.
    if conn.cursor_ms is None and os.environ.get("SATTI_SCHEDULER", "0") == "1":
        conn.last_sync_at = None  # сделаем подключение «due»: планировщик возьмёт его в ближайший проход
        conn.last_error = None
        db.add(conn)
        db.commit()
        return {"status": "queued", "added": 0, "updated": 0, "pages": 0,
                "message": "Первая загрузка заказов запущена в фоне. Обычно это занимает от 10 минут до часа."}
    client = None
    try:
        client = kaspi_service.client_for(conn)
        stats = kaspi_service.sync(db, conn, client, utcnow())
    except kaspi_service.KaspiBusy as exc:
        raise ApiError(409, "kaspi_sync_running", "Синхронизация уже идёт. Дождитесь окончания.") from exc
    except KaspiAuthError as exc:
        raise ApiError(422, "kaspi_token_rejected", "Kaspi не принимает ключ. Подключите магазин заново.") from exc
    except KaspiUnavailable as exc:
        raise ApiError(503, "kaspi_unavailable", "Kaspi сейчас недоступен. Попробуйте позже.") from exc
    finally:
        if client is not None:
            client.close()
    return {**stats, "status": "synced"}


@api.delete("/shops/{shop_id}/kaspi/connection", tags=["Kaspi"])
def kaspi_disconnect(shop_id: str, principal: Principal = Depends(get_principal), db: DbSession = Depends(get_session)) -> dict:
    """К-21 (решение владельца 01:24): отдельного отключения Kaspi нет — только удаление или деактивация аккаунта.
    Иначе «отключить и подключить снова» обходило бы правило «токен подключается один раз»."""
    _require_kaspi(db)
    shop_for(db, principal, shop_id, guard_access=False)
    raise ApiError(409, "kaspi_disconnect_removed",
                   "Отдельного отключения Kaspi нет. Прекратить работу можно удалением или деактивацией аккаунта.")


class EventIn(BaseModel):
    event: str = Field(min_length=1, max_length=64)


class EventsIn(BaseModel):
    events: list[str] = Field(min_length=1, max_length=50)


@api.post("/analytics/batch", status_code=204, tags=["аналитика"], include_in_schema=False)
def analytics_batch(body: EventsIn, request: Request) -> Response:
    """3.9: пакет событий из приложения (до 50 за раз). Только при ANALYTICS_ENABLED=1 и флаге в админке."""
    from .db import SessionLocal

    if not settings.analytics_enabled:
        raise ApiError(404, "not_found")
    if any(e not in analytics_service.ALLOWED_EVENTS for e in body.events):
        raise ApiError(422, "validation", "Неизвестное событие.")
    with SessionLocal() as db:
        if not allow(f"analytics-batch:{client_ip(request)}", 120, db=db):  # 1.16: одна сессия на запрос
            raise ApiError(429, "rate_limited", "Слишком много пакетов. Попробуйте позже.")
        if not is_enabled(db, "analytics"):
            raise ApiError(404, "not_found")
        for event in body.events:
            analytics_service.record(db, event, utcnow())
    return Response(status_code=204)


@api.post("/analytics/events", status_code=204, tags=["аналитика"])
def analytics_event(body: EventIn, request: Request) -> Response:
    """3.9: счётчик события за день. Без входа, без адреса и устройства; не чаще 600 раз в час с одного адреса."""
    if body.event not in analytics_service.ALLOWED_EVENTS:
        raise ApiError(422, "validation", "Неизвестное событие.")
    from .db import SessionLocal

    with SessionLocal() as db:
        if not allow(f"analytics:{client_ip(request)}", 600, db=db):  # 1.16: одна сессия на запрос
            raise ApiError(429, "rate_limited", "Слишком много событий. Попробуйте позже.")
        analytics_service.record(db, body.event, utcnow())
    return Response(status_code=204)


@api.get("/kaspi/price/{shop_id}/{price_key}", tags=["Kaspi"], include_in_schema=False)
def kaspi_price_list(shop_id: str, price_key: str, db: DbSession = Depends(get_session)) -> Response:
    """Прайс-лист для кабинета Kaspi. Доступ — по секрету в адресе (price_key), без входа в приложение."""
    _require_kaspi(db)
    shop = db.get(Shop, shop_id)
    conn = kaspi_service.find_by_price_key(db, shop_id, price_key) if shop else None
    if conn is None:
        raise ApiError(404, "not_found")
    if shop.presentation_mode:
        # К-33 А3: в режиме презентации остатки — пример; в магазин Kaspi ничего не уходит. Временная ошибка без файла:
        # Kaspi оставит прежний прайс продавца как есть.
        return Response(status_code=503, headers={"Retry-After": "3600"})
    if shop.id in accounts_service.deactivated_shop_ids(db):
        # К-21: пустой файл или available="no" сняли бы товары продавца с продажи. Отдаём временную ошибку без файла.
        return Response(status_code=503, headers={"Retry-After": "3600"})
    if kaspi_service.store_list(conn) and not kaspi_service.refresh_before_price(db, conn, datetime.now(timezone.utc)):
        # К-33 А4: заказы не досинхронизированы — прайс не отдаём: Kaspi оставит свой текущий остаток (он уже учёл
        # свои заказы). Старый файл «вернул» бы проданные единицы. Без кодов складов наличие не передаётся вовсе.
        return Response(status_code=503, headers={"Retry-After": "600"})
    try:
        body = kaspi_service.price_list_xml(db, shop, conn)
    except kaspi_service.KaspiNoCatalog as exc:
        raise ApiError(409, "catalog_not_imported", "Прайс-лист ещё не загружен из кабинета Kaspi.") from exc
    return Response(content=body, media_type="application/xml")
