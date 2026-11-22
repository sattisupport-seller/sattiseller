"""3.6 и 1.4: почта через SMTP (или outbox без адреса сервера), ошибки без адресов, оповещения владельцу о бюджете ИИ."""

import logging
import smtplib
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy.orm import Session as DbSession

from app import ai as ai_service
from app.config import settings
from app.db import engine
from app.mailer import MailError, send_code_email, send_owner_alert
from app.models import AIBudgetAlert


class FakeSMTP:
    sent: list = []
    fail: Exception | None = None

    def __init__(self, host, port, timeout=None):
        self.host, self.port = host, port

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self, context=None):
        pass

    def login(self, user, password):
        pass

    def send_message(self, msg):
        if FakeSMTP.fail is not None:
            raise FakeSMTP.fail
        FakeSMTP.sent.append((self.host, self.port, msg["To"], msg["Subject"], msg.get_content()))


@pytest.fixture
def smtp(monkeypatch):
    FakeSMTP.sent = []
    FakeSMTP.fail = None
    monkeypatch.setattr(settings, "smtp_host", "smtp.example.invalid")
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    return FakeSMTP


def test_code_goes_through_smtp_when_configured(smtp):
    send_code_email("seller@example.invalid", "123456", "login", "ru")  # К-13: письма только на русском
    host, port, to, subject, body = smtp.sent[0]
    assert host == "smtp.example.invalid" and port == settings.smtp_port
    assert to == "seller@example.invalid"
    assert "123456" in body and "Satti Seller" in subject


def test_code_goes_to_outbox_without_smtp(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "smtp_host", "")
    monkeypatch.setattr(settings, "outbox_dir", tmp_path / "outbox")
    send_code_email("seller@example.invalid", "654321", "login")
    files = list((tmp_path / "outbox").glob("*.eml"))
    assert len(files) == 1 and "654321" in files[0].read_text(encoding="utf-8")


def test_smtp_failure_raises_mail_error_without_the_address(smtp, caplog):
    smtp.fail = smtplib.SMTPException("550 mailbox unavailable")
    caplog.set_level(logging.DEBUG)
    with pytest.raises(MailError):
        send_code_email("private.person@example.invalid", "111222", "login")
    assert "private.person" not in caplog.text and "111222" not in caplog.text


def test_api_maps_mail_failure_to_503(client, monkeypatch):
    def broken(*args, **kwargs):
        raise MailError("почта недоступна")

    monkeypatch.setattr("app.api.send_code_email", broken)
    r = client.post("/v1/auth/email/start", json={"email": "seller@example.invalid"})
    assert r.status_code == 503 and r.json()["error"]["code"] == "mail_unavailable"


def test_owner_alert_needs_an_address(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "smtp_host", "")
    monkeypatch.setattr(settings, "outbox_dir", tmp_path / "outbox")
    monkeypatch.setattr(settings, "owner_alert_email", "")
    assert send_owner_alert("тема", "текст") is False
    monkeypatch.setattr(settings, "owner_alert_email", "owner@example.invalid")
    assert send_owner_alert("тема", "текст") is True


def _state(level, spent=8.0, budget=10.0):
    return {"level": level, "monthSpentUsd": spent, "monthBudgetUsd": budget,
            "daySpentUsd": 0.0, "dayBudgetUsd": 0.5}


def test_budget_alerts_are_sent_once_per_level(monkeypatch):
    monkeypatch.setattr(settings, "owner_alert_email", "owner@example.invalid")
    sent: list[str] = []
    monkeypatch.setattr(ai_service, "send_owner_alert", lambda subject, text: sent.append(subject) or True)
    now = datetime(2026, 11, 21, 12, 0, tzinfo=timezone.utc)
    states = iter(["ok", "warn", "warn", "exhausted", "exhausted"])
    with DbSession(engine) as db:
        for expected_level in ["ok", "warn", "warn", "exhausted", "exhausted"]:
            level = next(states)
            monkeypatch.setattr(ai_service, "budget_state", lambda db_, now_, lv=level: _state(lv, spent=10.0 if lv == "exhausted" else 8.0))
            ai_service.check_budget_alerts(db, now)
            db.commit()
        rows = db.query(AIBudgetAlert).all()
        assert sorted(r.level for r in rows) == ["exhausted", "warn"]
    assert len(sent) == 2
    assert "80%" in sent[0] and "исчерпан" in sent[1]


def test_failed_delivery_is_retried_later(monkeypatch):
    monkeypatch.setattr(settings, "owner_alert_email", "owner@example.invalid")
    attempts = []

    def flaky(subject, text):
        attempts.append(subject)
        if len(attempts) == 1:
            raise MailError("почта недоступна")
        return True

    monkeypatch.setattr(ai_service, "send_owner_alert", flaky)
    monkeypatch.setattr(ai_service, "budget_state", lambda db_, now_: _state("warn"))
    now = datetime(2026, 11, 22, 9, 0, tzinfo=timezone.utc)
    with DbSession(engine) as db:
        assert ai_service.check_budget_alerts(db, now) == []
        db.commit()
        assert ai_service.check_budget_alerts(db, now) == ["warn"]
        db.commit()
    assert len(attempts) == 2


def test_no_alert_while_budget_is_ok(monkeypatch):
    monkeypatch.setattr(ai_service, "send_owner_alert", lambda s, t: pytest.fail("не должно отправляться"))
    monkeypatch.setattr(ai_service, "budget_state", lambda db_, now_: _state("ok", spent=1.0))
    with DbSession(engine) as db:
        assert ai_service.check_budget_alerts(db, datetime.now(timezone.utc)) == []


def test_recording_usage_checks_alerts(monkeypatch):
    """record_usage сам проверяет бюджет: уровень ok — ничего не пишется."""
    monkeypatch.setattr(ai_service, "send_owner_alert", lambda s, t: pytest.fail("не должно отправляться"))
    now = datetime.now(timezone.utc)
    with DbSession(engine) as db:
        ai_service.record_usage(db, None, f"shop-{uuid.uuid4().hex[:6]}", now, "question")
        db.commit()
        assert db.query(AIBudgetAlert).count() == 0
