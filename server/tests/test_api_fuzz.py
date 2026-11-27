"""QA этап 3: фаззинг всех операций OpenAPI (schemathesis).

Цель: ни одна операция не отвечает 5xx на неверные типы, пустые поля, огромные значения, юникод и
строки, похожие на SQL/скрипты, и ответ соответствует схеме. Нормальный ход — 2xx/4xx.
Число примеров ограничено (SATTI_FUZZ_EXAMPLES, по умолчанию 15), чтобы прогон занимал минуты.
"""

import os

import pytest
import schemathesis
from fastapi.testclient import TestClient
from hypothesis import HealthCheck, settings
from schemathesis.checks import not_a_server_error, response_schema_conformance

from app.main import app

EXAMPLES = int(os.environ.get("SATTI_FUZZ_EXAMPLES", "15"))
schema = schemathesis.openapi.from_asgi("/v1/openapi.json", app)


@pytest.fixture(scope="module")
def auth_headers():
    with TestClient(app) as c:
        r = c.post("/v1/demo/session", headers={"X-Device-Id": "fuzz-device-0001"})
        assert r.status_code == 200
        token = r.json()["access_token"]
        c.post("/v1/ai/consent", json={"granted": True}, headers={"Authorization": f"Bearer {token}"})
        return {"Authorization": f"Bearer {token}"}


def _real_server_error_only(ctx, response, case):
    # 503 с кодом provider_* — намеренный ответ «вход не настроен» (ТЗ 2.1, раздел 5), а не ошибка сервера
    if response.status_code == 503 and b"provider_" in response.content:
        return True
    return not_a_server_error(ctx, response, case)


@schema.parametrize()
@settings(max_examples=EXAMPLES, deadline=None, suppress_health_check=list(HealthCheck))
def test_no_server_errors(case, auth_headers):
    case.call_and_validate(headers=auth_headers, checks=[_real_server_error_only, response_schema_conformance])


@pytest.fixture(scope="module")
def account_headers():
    """6.3 (К-21): фаззинг с входом в настоящий аккаунт — эндпоинты аккаунта (удаление, деактивация, пуши, настройки,
    подписка), которые демо-сессии отвечают 403. Аккаунт с магазином и подтверждённым возрастом."""
    from tests.conftest import confirm_age, login

    with TestClient(app) as c:
        tokens = login(c, "fuzz-account@example.invalid")
        headers = {"Authorization": f"Bearer {tokens['access_token']}"}
        confirm_age(c, headers)
        c.post("/v1/shops", headers=headers, json={"name": "Фаззинг"})
        return headers


@schema.parametrize()
@settings(max_examples=EXAMPLES, deadline=None, suppress_health_check=list(HealthCheck))
def test_no_server_errors_with_account(case, account_headers):
    case.call_and_validate(headers=account_headers, checks=[_real_server_error_only, response_schema_conformance])
