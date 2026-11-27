"""3.4 (MASTER_PLAN, К-21): пуши на моке — токен устройства, очередь, тихие часы, сводка по понедельникам, склад,
настройки; деактивированный и удалённый аккаунт уведомлений не получает."""

import json
from datetime import datetime, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app import push
from app.config import settings
from app.db import engine
from app.models import User
from tests.conftest import confirm_age, login

TOKEN = "ExponentPushToken[abcdefghijklmnop]"


def _account(client, email, monkeypatch):
    monkeypatch.setattr(settings, "billing_enforced", False)
    tokens = login(client, email)
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    confirm_age(client, headers)
    shop_id = client.post("/v1/shops", headers=headers, json={"name": "Магазин"}).json()["id"]
    return headers, shop_id, tokens["user"]["id"]


def _push_files():
    folder = settings.outbox_dir / "push"
    return [json.loads(f.read_text(encoding="utf-8")) for f in folder.glob("*.json")] if folder.exists() else []


def test_quiet_hours_move_to_9_almaty():
    night = datetime(2026, 11, 27, 18, 30, tzinfo=timezone.utc)  # 23:30 по Алматы
    assert push.send_time(night, quiet=True) == datetime(2026, 11, 28, 4, 0, tzinfo=timezone.utc)  # 09:00 Алматы
    early = datetime(2026, 11, 27, 1, 0, tzinfo=timezone.utc)  # 06:00 по Алматы
    assert push.send_time(early, quiet=True) == datetime(2026, 11, 27, 4, 0, tzinfo=timezone.utc)
    day = datetime(2026, 11, 27, 7, 0, tzinfo=timezone.utc)  # 12:00
    assert push.send_time(day, quiet=True) == day
    assert push.send_time(night, quiet=False) == night


def test_token_registration_and_mock_delivery(client, monkeypatch):
    headers, _, user_id = _account(client, "push1@example.com", monkeypatch)
    assert client.post("/v1/devices/push-token", headers=headers, json={"token": TOKEN, "platform": "ios"}).status_code == 204
    before = len(_push_files())
    with DbSession(engine) as db:
        assert push.enqueue(db, user_id, "stock", "Склад: Кружка", "Остаток: 3 шт.", {"screen": "stock"})
        db.commit()
        assert push.dispatch_due(db) == 1
    files = _push_files()
    assert len(files) == before + 1 and any(f["to"] == TOKEN and f["data"]["screen"] == "stock" for f in files)


def test_settings_are_read_back_and_weekly_respects_them(client, monkeypatch):
    headers, _, user_id = _account(client, "push2@example.com", monkeypatch)
    assert client.get("/v1/notification-settings", headers=headers).json() == {
        "product_in_minus": False, "weekly_summary": False, "quiet_hours": False}
    client.patch("/v1/notification-settings", headers=headers, json={"weekly_summary": True})
    client.patch("/v1/notification-settings", headers=headers, json={"quiet_hours": True})
    got = client.get("/v1/notification-settings", headers=headers).json()
    assert got == {"product_in_minus": False, "weekly_summary": True, "quiet_hours": True}  # частичное изменение
    with DbSession(engine) as db:
        assert push.enqueue(db, user_id, "minus", "Товар в минусе", "…") is None  # выключено в настройках


def test_weekly_summary_on_monday_9_once(client, monkeypatch):
    headers, _, user_id = _account(client, "push3@example.com", monkeypatch)
    client.patch("/v1/notification-settings", headers=headers, json={"weekly_summary": True})
    monday_9 = datetime(2026, 11, 30, 4, 10, tzinfo=timezone.utc)  # понедельник, 09:10 по Алматы
    with DbSession(engine) as db:
        assert push.weekly_summary_due(db, datetime(2026, 11, 29, 4, 10, tzinfo=timezone.utc)) == 0  # воскресенье
        push.weekly_summary_due(db, monday_9)
        push.weekly_summary_due(db, monday_9)  # повтор в тот же час — без дубля
        msgs = db.scalars(select(push.PushMessage).where(push.PushMessage.user_id == user_id,
                                                         push.PushMessage.kind == "weekly")).all()
    assert len(msgs) == 1 and "Заказов" in msgs[0].body


def test_deactivated_and_deleted_accounts_get_nothing(client, monkeypatch):
    headers, _, user_id = _account(client, "push4@example.com", monkeypatch)
    client.post("/v1/devices/push-token", headers=headers, json={"token": TOKEN + "4", "platform": "android"})
    with DbSession(engine) as db:
        push.enqueue(db, user_id, "stock", "Склад", "Остаток: 0 шт.")
        db.get(User, user_id).deactivated_at = datetime.now(timezone.utc)
        db.commit()
        assert push.dispatch_due(db) == 0  # в очереди было — не отправлено
        assert push.enqueue(db, user_id, "stock", "Склад", "ещё") is None
        from app.accounts import delete_user_account

        delete_user_account(db, db.get(User, user_id))
        assert db.scalars(select(push.DeviceToken).where(push.DeviceToken.user_id == user_id)).all() == []
        assert db.scalars(select(push.PushMessage).where(push.PushMessage.user_id == user_id)).all() == []


def test_expo_mode_sends_and_forgets_dead_tokens(client, monkeypatch):
    headers, _, user_id = _account(client, "push5@example.com", monkeypatch)
    client.post("/v1/devices/push-token", headers=headers, json={"token": TOKEN + "5", "platform": "ios"})
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={"data": [{"status": "error", "message": "x",
                                                   "details": {"error": "DeviceNotRegistered"}}]})

    monkeypatch.setattr(settings, "push_mode", "expo")
    monkeypatch.setattr(push, "transport", httpx.MockTransport(handler))
    with DbSession(engine) as db:
        push.enqueue(db, user_id, "stock", "Склад", "Остаток: 3 шт.")
        db.commit()
        assert push.dispatch_due(db) == 1
        assert db.get(push.DeviceToken, TOKEN + "5") is None  # Expo: устройство больше не зарегистрировано
    assert seen[0][0]["to"] == TOKEN + "5"


def test_logout_removes_token(client, monkeypatch):
    headers, _, _ = _account(client, "push6@example.com", monkeypatch)
    client.post("/v1/devices/push-token", headers=headers, json={"token": TOKEN + "6", "platform": "ios"})
    r = client.request("DELETE", "/v1/devices/push-token", headers=headers, json={"token": TOKEN + "6", "platform": "ios"})
    assert r.status_code == 204
    with DbSession(engine) as db:
        assert db.get(push.DeviceToken, TOKEN + "6") is None
