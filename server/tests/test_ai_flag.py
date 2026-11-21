"""Выключатель помощника: по умолчанию выключен; при выключенном флаге вопросы отклоняются 503, конфиг сообщает флаг."""

from sqlalchemy.orm import Session as DbSession

from app.admin import FeatureFlag
from app.db import engine


def _set_flag(enabled: bool) -> None:
    with DbSession(engine) as s:
        row = s.get(FeatureFlag, "ai_assistant")
        row.enabled = enabled
        s.commit()


def test_default_is_off_for_launch():
    from app.admin import FLAG_DEFAULTS
    assert FLAG_DEFAULTS["ai_assistant"] is False


def test_question_is_refused_when_flag_is_off(client, demo):
    _set_flag(False)
    client.post("/v1/ai/consent", headers=demo["headers"], json={"granted": True})
    r = client.post(f"/v1/shops/{demo['shop_id']}/ai/ask", headers=demo["headers"], json={"question": "Сколько заказов вчера?"})
    assert r.status_code == 503
    assert r.json()["error"]["code"] == "ai_disabled"


def test_config_reports_flag_state(client):
    _set_flag(False)
    assert client.get("/v1/app/config").json()["flags"]["ai_assistant"] is False
    _set_flag(True)
    assert client.get("/v1/app/config").json()["flags"]["ai_assistant"] is True
