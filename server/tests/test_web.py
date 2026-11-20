"""Публичные страницы и веб-удаление аккаунта (ТЗ 2.1, 13.2 и 24)."""

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.config import settings
from app.db import engine
from app.models import User
from tests.conftest import confirm_age, login


def test_privacy_and_terms_are_served_as_drafts(client):
    for path, marker in (("/privacy", "Политика конфиденциальности"), ("/terms", "Пользовательское соглашение")):
        r = client.get(path)
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/html")
        assert marker in r.text
        assert "ЧЕРНОВИК ДЛЯ ЮРИСТА" in r.text


def test_delete_form_is_public(client):
    r = client.get("/delete-account")
    assert r.status_code == 200
    assert 'name="email"' in r.text


def test_web_delete_removes_account_with_code(client):
    tokens = login(client, "webdel@example.com")
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    confirm_age(client, headers)
    client.post("/v1/shops", headers=headers, json={"name": "Удаляемый", "timezone": "Asia/Almaty", "language": "ru"})

    assert client.post("/delete-account/start", data={"email": "webdel@example.com"}).status_code == 200
    # код не показывается на странице; берём его из письма в outbox, как в разработке
    mails = [m.read_text(encoding="utf-8") for m in sorted(settings.outbox_dir.glob("*.eml"))]
    code = [m for m in mails if "webdel@example.com" in m and "удаления" in m][-1].split("Ваш код: ")[1].split()[0]

    done = client.post("/delete-account/confirm", data={"email": "webdel@example.com", "code": code})
    assert done.status_code == 200
    assert "Аккаунт удалён" in done.text
    with DbSession(engine) as db:
        assert db.scalar(select(User).where(User.email == "webdel@example.com")) is None


def test_unknown_email_gets_same_answer(client):
    r = client.post("/delete-account/start", data={"email": "nobody@example.com"})
    assert r.status_code == 200
    assert "Если аккаунт" in r.text


def test_wrong_code_is_refused(client):
    login(client, "wrongcode@example.com")
    r = client.post("/delete-account/confirm", data={"email": "wrongcode@example.com", "code": "000000"})
    assert "Код неверный" in r.text


def test_favicon_is_served(client):
    r = client.get("/favicon.ico")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"
