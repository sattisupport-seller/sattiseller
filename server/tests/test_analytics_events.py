"""3.9 (К-21): события из списка сервера действительно записываются (счётчики за день, без персональных данных).
Расхождение 27.11: 13 событий из списка никто не записывал; перенос телефона больше не существует (К-21, 01:53)."""

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app import analytics
from app.config import settings
from app.db import engine
from tests.conftest import confirm_age, login


def _count(event: str) -> int:
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    with DbSession(engine) as db:
        rows = db.execute(select(analytics.AnalyticsDaily).where(analytics.AnalyticsDaily.event == event,
                                                                 analytics.AnalyticsDaily.day == day)).scalars().all()
        return sum(r.count for r in rows)


def test_device_transfer_events_removed():
    assert "device_transfer_started" not in analytics.ALLOWED_EVENTS
    assert "device_transfer_completed" not in analytics.ALLOWED_EVENTS


def test_server_records_auth_export_and_tax_events(client, monkeypatch):
    monkeypatch.setattr(settings, "billing_enforced", False)
    before = {e: _count(e) for e in ("auth_method_used", "data_export_requested", "tax_rate_saved", "excel_exported")}
    tokens = login(client, "events@example.com")
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    confirm_age(client, headers)
    shop_id = client.post("/v1/shops", headers=headers, json={"name": "Магазин"}).json()["id"]
    assert client.get("/v1/me/export", headers=headers).status_code == 200
    assert client.post(f"/v1/shops/{shop_id}/tax", headers=headers,
                       json={"enabled": True, "rate_percent": "3"}).status_code == 201
    assert client.get(f"/v1/shops/{shop_id}/exports/profit.xlsx", headers=headers).status_code == 200
    for event, n in before.items():
        assert _count(event) == n + 1, event
