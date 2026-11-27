"""Push-уведомления (MASTER_PLAN 3.4, К-21) — на моке до подключения Firebase и APNs.

Устройство: приложение получает Expo push token (expo-notifications) и регистрирует его на сервере
(`POST /v1/devices/push-token`). Токен привязан к аккаунту; при выходе — удаляется.

Отправка: `enqueue()` кладёт уведомление в очередь `push_messages` с временем отправки. Тихие часы (22:00–09:00 по
Алматы, если включены в настройках) переносят отправку на 09:00. `dispatch_due()` (раз в несколько минут из
планировщика) отправляет созревшие: на моке — файл в outbox/push; в бою — Expo Push API
(https://exp.host/--/api/v2/push/send), который доставляет через FCM и APNs по ключам из EAS.

Что уходит: склад (остаток 10/5/3/0), сводка по понедельникам в 09:00, товар в минусе (по настройке).
Без персональных данных покупателей: только название товара, числа магазина и экран, который открыть.
Деактивированный аккаунт уведомлений не получает.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import Boolean, DateTime, String, Text, select
from sqlalchemy.orm import Mapped, Session as DbSession, mapped_column

from .config import settings
from .db import Base

log = logging.getLogger("satti.push")
ALMATY = ZoneInfo("Asia/Almaty")
QUIET_FROM, QUIET_TO = time(22, 0), time(9, 0)
EXPO_URL = "https://exp.host/--/api/v2/push/send"
transport: httpx.BaseTransport | None = None  # в тестах — httpx.MockTransport


def _uid() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(timezone.utc)


class DeviceToken(Base):
    __tablename__ = "device_tokens"
    token: Mapped[str] = mapped_column(String(255), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(32), index=True)
    platform: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class PushMessage(Base):
    __tablename__ = "push_messages"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uid)
    user_id: Mapped[str] = mapped_column(String(32), index=True)
    kind: Mapped[str] = mapped_column(String(24))  # stock | weekly | minus
    dedup_key: Mapped[str | None] = mapped_column(String(128), nullable=True, unique=True)
    title: Mapped[str] = mapped_column(String(120))
    body: Mapped[str] = mapped_column(String(300))
    data_json: Mapped[str] = mapped_column(Text, default="{}")
    send_after: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    dropped: Mapped[bool] = mapped_column(Boolean, default=False)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def send_time(now: datetime, quiet: bool) -> datetime:
    """Когда отправить: сразу или, в тихие часы, в 09:00 по Алматы."""
    if not quiet:
        return now
    local = _aware(now).astimezone(ALMATY)
    t = local.time()
    if QUIET_TO <= t < QUIET_FROM:
        return now
    day = local.date() if t < QUIET_TO else local.date() + timedelta(days=1)
    return datetime.combine(day, QUIET_TO, tzinfo=ALMATY).astimezone(timezone.utc)


def _settings_of(db: DbSession, user_id: str):
    from .models import NotificationSettings

    return db.get(NotificationSettings, user_id)


def enqueue(db: DbSession, user_id: str | None, kind: str, title: str, body: str, data: dict | None = None,
            dedup_key: str | None = None, now: datetime | None = None) -> PushMessage | None:
    """Кладёт уведомление в очередь. Нет аккаунта, деактивирован, выключено в настройках, повтор — None."""
    from .models import User

    if not user_id:
        return None
    user = db.get(User, user_id)
    if user is None or user.deactivated_at is not None:
        return None
    prefs = _settings_of(db, user_id)
    if kind == "weekly" and not (prefs and prefs.weekly_summary):
        return None
    if kind == "minus" and not (prefs and prefs.product_in_minus):
        return None
    if dedup_key and db.scalar(select(PushMessage.id).where(PushMessage.dedup_key == dedup_key)) is not None:
        return None
    now = now or _now()
    msg = PushMessage(user_id=user_id, kind=kind, dedup_key=dedup_key, title=title[:120], body=body[:300],
                      data_json=json.dumps(data or {}, ensure_ascii=False),
                      send_after=send_time(now, bool(prefs and prefs.quiet_hours)))
    db.add(msg)
    db.flush()
    return msg


def _deliver_mock(token: str, msg: PushMessage) -> None:
    folder = settings.outbox_dir / "push"
    folder.mkdir(parents=True, exist_ok=True)
    payload = {"to": token, "title": msg.title, "body": msg.body, "data": json.loads(msg.data_json), "kind": msg.kind}
    (folder / f"{_now():%Y%m%dT%H%M%S%f}_{msg.id}.json").write_text(json.dumps(payload, ensure_ascii=False),
                                                                     encoding="utf-8")


def _deliver_expo(tokens: list[str], msg: PushMessage) -> list[str]:
    """Expo Push API. Возвращает токены, которые Expo считает недействительными (их удаляем)."""
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if settings.expo_access_token:
        headers["Authorization"] = f"Bearer {settings.expo_access_token}"
    body = [{"to": t, "title": msg.title, "body": msg.body, "data": json.loads(msg.data_json), "sound": "default"}
            for t in tokens]
    with httpx.Client(timeout=15.0, transport=transport) as http:
        r = http.post(EXPO_URL, json=body, headers=headers)
    r.raise_for_status()
    dead = []
    for token, ticket in zip(tokens, r.json().get("data", [])):
        if ticket.get("status") == "error" and (ticket.get("details") or {}).get("error") == "DeviceNotRegistered":
            dead.append(token)
    return dead


def dispatch_due(db: DbSession, now: datetime | None = None, limit: int = 500) -> int:
    """Отправляет созревшие уведомления. Возвращает число отправленных сообщений."""
    from .models import User

    now = now or _now()
    due = db.scalars(select(PushMessage).where(PushMessage.sent_at.is_(None), PushMessage.dropped.is_(False),
                                               PushMessage.send_after <= now)
                     .order_by(PushMessage.send_after).limit(limit)).all()
    sent = 0
    for msg in due:
        user = db.get(User, msg.user_id)
        tokens = list(db.scalars(select(DeviceToken.token).where(DeviceToken.user_id == msg.user_id)).all())
        if user is None or user.deactivated_at is not None or not tokens:
            msg.dropped = True  # некуда или нельзя отправлять — не копим
            continue
        try:
            if settings.push_mode == "expo":
                for token in _deliver_expo(tokens, msg):
                    db.query(DeviceToken).filter(DeviceToken.token == token).delete()
            else:
                for token in tokens:
                    _deliver_mock(token, msg)
        except httpx.HTTPError as exc:
            log.warning("push delivery failed: %s", type(exc).__name__)  # повторим в следующий проход
            continue
        msg.sent_at = now
        sent += 1
    db.commit()
    return sent


def weekly_summary_due(db: DbSession, now: datetime | None = None) -> int:
    """Сводка по понедельникам в 09:00 по Алматы (запуск — раз в час). Один раз в неделю на аккаунт (dedup_key)."""
    from .models import Shop
    from .periods import resolve
    from .reports import base_for, overview

    now = now or _now()
    local = _aware(now).astimezone(ALMATY)
    if local.weekday() != 0 or local.hour != 9:
        return 0
    week = local.strftime("%G-W%V")
    count = 0
    for shop in db.scalars(select(Shop).where(Shop.is_demo.is_(False))).all():
        try:
            data, facts = base_for(db, shop)
            ov = overview(data, facts, resolve("7d", shop.timezone), now)
        except Exception:  # noqa: BLE001 — сводка одного магазина не останавливает остальные
            log.exception("weekly summary failed for shop %s", shop.id)
            continue
        kpi = ov.get("kpi", {})
        profit = kpi.get("profit_minor")
        orders = kpi.get("orders_count", 0)
        from .money import format_tenge

        text = (f"Заказов: {orders}. Прибыль: {format_tenge(profit)}." if profit is not None
                else f"Заказов: {orders}. Прибыль не посчитана: укажите себестоимость.")
        if enqueue(db, shop.owner_user_id, "weekly", "Сводка за неделю", text, {"screen": "overview"},
                   dedup_key=f"weekly:{shop.owner_user_id}:{week}", now=now):
            count += 1
    db.commit()
    return count
