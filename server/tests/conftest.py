import os
import tempfile
from pathlib import Path

# Изоляция: тестовая база и папка писем во временной папке, до импорта приложения.
_tmp = Path(tempfile.mkdtemp(prefix="satti-test-"))
# SATTI_TEST_DATABASE_URL — прогон на PostgreSQL (QA-01); без неё — SQLite во временной папке
os.environ["DATABASE_URL"] = os.environ.get("SATTI_TEST_DATABASE_URL") or f"sqlite:///{(_tmp / 'test.db').as_posix()}"
os.environ["SATTI_OUTBOX_DIR"] = str(_tmp / "outbox")
os.environ["SATTI_DATA_DIR"] = str(_tmp / "data")
os.environ["SATTI_EMAIL_LOGIN"] = "1"  # только тесты: вход по коду на почту

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import ratelimit  # noqa: E402
from app.db import Base, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.admin import FeatureFlag  # noqa: E402
from sqlalchemy.orm import Session as DbSession  # noqa: E402

from app.config import settings  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh_db():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    # Помощник включён (решение владельца 22.11). Живая модель в тестах выключена принудительно:
    # ключ в .env есть, а платные вызовы — только в тестах с фикстурой live.
    with DbSession(engine) as s:
        s.add(FeatureFlag(key="ai_assistant", enabled=True))
        s.commit()
    settings.ai_live = False
    ratelimit.reset()
    yield


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def demo(client):
    r = client.post("/v1/demo/session", headers={"X-Device-Id": "test-device-0001"})
    assert r.status_code == 200, r.text
    body = r.json()
    headers = {"Authorization": f"Bearer {body['access_token']}"}
    return {"shop_id": body["shop_id"], "headers": headers, "refresh": body["refresh_token"]}


def login(client, email: str, accept_terms: bool = True) -> dict:
    """Вход по email-коду: код берётся из папки писем (outbox), как в разработке.
    accept_terms — галочка условий на экране входа (1.19); по умолчанию принята, как в приложении."""
    from app.config import settings

    outbox = settings.outbox_dir
    before = set(outbox.glob("*.eml")) if outbox.exists() else set()
    assert client.post("/v1/auth/email/start", json={"email": email}).status_code == 202
    new = sorted(set(outbox.glob("*.eml")) - before)
    code = new[-1].read_text(encoding="utf-8").split("Ваш код: ")[1].split()[0]
    r = client.post("/v1/auth/email/verify", json={"email": email, "code": code, "accept_terms": accept_terms})
    assert r.status_code == 200, r.text
    return r.json()


def confirm_age(client, headers) -> None:
    """Подтверждение 18+ перед созданием магазина (ADR-0004)."""
    r = client.post("/v1/me/age-confirm", headers=headers)
    assert r.status_code == 200, r.text


@pytest.fixture
def admin_email(monkeypatch):
    """Владелец панели для тестов админки (общая фикстура, см. test_admin.py)."""
    from app.config import settings

    monkeypatch.setattr(settings, "admin_email", "boss@example.com")
    return "boss@example.com"
