"""Админка: жалобы «Пожаловаться» и 👎 на ответы помощника — списком, без «👍» и без персональных данных."""

from sqlalchemy.orm import Session as DbSession

from app.db import engine
from app.models import AIFeedback
from tests.test_admin import _admin_headers, _enable_2fa, _headers, admin_email  # noqa: F401  (фикстура)


def test_admin_lists_complaints_and_thumbs_down_only(client, admin_email):  # noqa: F811
    headers = _headers(client, admin_email)
    secret = _enable_2fa(client, headers)
    ah = _admin_headers(client, headers, secret)
    with DbSession(engine) as db:
        db.add_all([
            AIFeedback(shop_id="s1", kind="up", question_masked="ok?"),
            AIFeedback(shop_id="s1", kind="down", reason="wrong_numbers", question_masked="Прибыль за неделю"),
            AIFeedback(shop_id="s1", kind="flag", reason="rude", question_masked="Поставь цену", refused=True,
                       refusal_category="write_action"),
        ])
        db.commit()
    r = client.get("/v1/admin/ai-feedback", headers=ah)
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert {i["kind"] for i in items} == {"down", "flag"}
    flag = next(i for i in items if i["kind"] == "flag")
    assert flag["refused"] is True and flag["refusal_category"] == "write_action"
    assert all(i["question"] for i in items)
