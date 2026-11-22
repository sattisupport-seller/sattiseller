"""Журнал чувствительных действий (К-2 п.8): запись есть, персональных данных в ней нет."""

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app import audit
from app.db import engine
from app.models import AuditEvent
from tests.conftest import login


def test_record_stores_only_action_and_ids():
    with DbSession(engine) as db:
        audit.record(db, "user_export", "user", actor_id="actor-1", shop_id="shop-1")
        row = db.scalars(select(AuditEvent).where(AuditEvent.actor_id == "actor-1")).one()
        assert (row.action, row.entity, row.result, row.shop_id) == ("user_export", "user", "ok", "shop-1")
        cols = {c.name for c in AuditEvent.__table__.columns}
        assert not cols & {"email", "phone", "name", "token", "ip"}  # персональных полей в журнале нет
        db.delete(row)
        db.commit()


def test_long_values_are_truncated_not_rejected():
    with DbSession(engine) as db:
        audit.record(db, "x" * 100, "y" * 100, result="z" * 40, actor_id="actor-long")
        row = db.scalars(select(AuditEvent).where(AuditEvent.actor_id == "actor-long")).one()
        assert len(row.action) == 64 and len(row.entity) == 64 and len(row.result) == 16
        db.delete(row)
        db.commit()


def test_export_writes_audit_event_with_actor(client):
    tokens = login(client, "audit-exporter@example.com")
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    assert client.get("/v1/me/export", headers=headers).status_code == 200
    with DbSession(engine) as db:
        rows = db.scalars(select(AuditEvent).where(AuditEvent.action == "user_export")).all()
        assert rows and all(r.actor_id for r in rows)
