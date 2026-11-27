"""Сбор ошибок на сервере (ТЗ 2.1, 14.4): группировка, маскировка, приём из приложения, просмотр в админке."""

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.config import settings
from app.db import engine
from app.errorlog import AppError, record_error, unhandled_error_response
from tests.test_admin import ADMIN, _admin_headers, _enable_2fa, _headers


def test_same_error_is_one_group_with_counter(client):
    with DbSession(engine) as db:
        fp1 = record_error(db, kind="server", exc_type="ValueError", where="GET /v1/x", message="первая")
        fp2 = record_error(db, kind="server", exc_type="ValueError", where="GET /v1/x", message="вторая")
        row = db.get(AppError, fp1)
    assert fp1 == fp2
    assert row.count == 2


def test_message_is_masked_before_storage(client):
    with DbSession(engine) as db:
        fp = record_error(db, kind="client", exc_type="ClientError", where="login",
                          message="Не сработало у +7 701 000 00 00, почта a@b.kz, ул. Абая 15")
        row = db.get(AppError, fp)
    assert "701" not in row.message
    assert "a@b.kz" not in row.message
    assert "Абая" not in row.message


def test_client_error_endpoint_records_and_is_anonymous(client):
    r = client.post("/v1/telemetry/errors", json={"where": "profit", "message": "boom", "app_version": "1.0.0",
                                                  "platform": "ios"})
    assert r.status_code == 202
    assert r.json()["status"] == "recorded"


def test_admin_sees_error_groups_others_do_not(client, monkeypatch):
    monkeypatch.setattr(settings, "admin_email", ADMIN)
    client.post("/v1/telemetry/errors", json={"where": "orders", "message": "не открылся заказ"})
    # обычный пользователь панель не видит
    seller = _headers(client, "seller-err@example.com")
    assert client.get("/v1/admin/errors", headers=seller).status_code == 404
    # владелец — с кодом 2FA
    owner = _headers(client, ADMIN)
    secret = _enable_2fa(client, owner)
    r = client.get("/v1/admin/errors", headers=_admin_headers(client, owner, secret))
    assert r.status_code == 200
    assert any(item["where"] == "orders" for item in r.json()["items"])


def test_unhandled_error_gets_generic_answer_and_is_logged(client):
    class _Req:
        method = "GET"
        scope: dict = {}

        class url:  # noqa: N801 — имитация объекта url
            path = "/v1/shops/abc/overview?period=7d"

    with DbSession(engine) as db:
        resp = unhandled_error_response(_Req(), RuntimeError("секрет +7 701 000 00 00"), db)
        groups = db.scalars(select(AppError).where(AppError.kind == "server")).all()
    assert resp.status_code == 500
    body = resp.body.decode("utf-8")
    assert "секрет" not in body and "701" not in body
    assert "error_id" in body
    assert any(g.where == "GET /v1/shops/abc/overview" for g in groups)
    assert all("701" not in g.message for g in groups)
