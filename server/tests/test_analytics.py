"""3.9: счётчики событий по дням без персональных данных; просмотр — в админке."""

from datetime import datetime, timezone

import pytest
from sqlalchemy import inspect
from sqlalchemy.orm import Session as DbSession

from app import analytics
from app import api as api_module
from app.config import settings
from app.db import engine
from app.kaspi_client import KaspiClient
from app.models import AnalyticsDaily
from tests.kaspi_mock import MockKaspi


def _count(event: str) -> int:
    with DbSession(engine) as db:
        return sum(r["count"] for r in analytics.summary(db, "2000-01-01") if r["event"] == event)


def test_record_counts_per_day_and_event():
    now = datetime(2026, 11, 21, 10, 0, tzinfo=timezone.utc)
    with DbSession(engine) as db:
        analytics.record(db, "paywall_shown", now)
        analytics.record(db, "paywall_shown", now)
        analytics.record(db, "trial_started", now)
        rows = {(r["day"], r["event"]): r["count"] for r in analytics.summary(db, "2026-01-01")}
    assert rows[("2026-11-21", "paywall_shown")] == 2
    assert rows[("2026-11-21", "trial_started")] == 1


def test_unknown_event_is_refused_in_code_and_api(client):
    with pytest.raises(analytics.UnknownEvent):
        with DbSession(engine) as db:
            analytics.record(db, "email_address_seen", datetime.now(timezone.utc))
    r = client.post("/v1/analytics/events", json={"event": "email_address_seen"})
    assert r.status_code == 422


def test_public_endpoint_counts_without_login(client):
    r = client.post("/v1/analytics/events", json={"event": "lock_screen_shown"})
    assert r.status_code == 204
    assert _count("lock_screen_shown") == 1


def test_endpoint_is_rate_limited(client, monkeypatch):
    monkeypatch.setattr(api_module, "allow", lambda key, limit, window=3600: False)
    r = client.post("/v1/analytics/events", json={"event": "restore_tapped"})
    assert r.status_code == 429


def test_table_has_no_personal_fields():
    cols = {c["name"] for c in inspect(engine).get_columns(AnalyticsDaily.__tablename__)}
    assert cols == {"day", "event", "count"}


def test_admin_summary_needs_admin(client):
    assert client.get("/v1/admin/analytics").status_code in (401, 403)


def test_kaspi_connect_events_are_counted(client, demo, monkeypatch):
    monkeypatch.setattr(settings, "kaspi_connection_enabled", True)
    from tests.test_kaspi import _set_admin_flag

    _set_admin_flag(True)
    m = MockKaspi()
    monkeypatch.setattr(api_module, "KaspiClient",
                        lambda token, **kw: KaspiClient(token, transport=m.transport(), sleep=lambda s: None, min_interval=0))
    before_started = _count("kaspi_connect_started")
    before_failed = _count("kaspi_connect_failed")
    r = client.post(f"/v1/shops/{demo['shop_id']}/kaspi/connection",
                    json={"seller_id": "S-1", "token": "wrong-token-0000000"}, headers=demo["headers"])
    assert r.status_code == 422
    assert _count("kaspi_connect_started") == before_started + 1
    assert _count("kaspi_connect_failed") == before_failed + 1


def _set_analytics_admin_flag(value: bool) -> None:
    from app.admin import FeatureFlag

    with DbSession(engine) as db:
        row = db.get(FeatureFlag, "analytics") or FeatureFlag(key="analytics")
        row.enabled = value
        row.updated_at = datetime.now(timezone.utc)
        db.add(row)
        db.commit()


def test_batch_is_off_by_default(client):
    r = client.post("/v1/analytics/batch", json={"events": ["lock_screen_shown"]})
    assert r.status_code == 404


def test_batch_needs_env_and_admin_flag(client, monkeypatch):
    monkeypatch.setattr(settings, "analytics_enabled", True)
    assert client.post("/v1/analytics/batch", json={"events": ["lock_screen_shown"]}).status_code == 404  # флага в админке нет
    _set_analytics_admin_flag(True)
    r = client.post("/v1/analytics/batch", json={"events": ["lock_screen_shown", "restore_tapped", "restore_tapped"]})
    assert r.status_code == 204
    assert _count("restore_tapped") == 2
    assert _count("lock_screen_shown") == 1


def test_batch_refuses_unknown_events_and_oversized_batches(client, monkeypatch):
    monkeypatch.setattr(settings, "analytics_enabled", True)
    _set_analytics_admin_flag(True)
    assert client.post("/v1/analytics/batch", json={"events": ["email_seen"]}).status_code == 422
    assert client.post("/v1/analytics/batch", json={"events": ["paywall_shown"] * 51}).status_code == 422


def test_app_config_reports_analytics_flag_off_by_default(client):
    body = client.get("/v1/app/config").json()
    assert body["flags"]["analytics"] is False
