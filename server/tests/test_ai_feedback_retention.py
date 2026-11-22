"""Хранение оценок помощника: 12 месяцев; при удалении аккаунта — сразу (решение владельца 22.11)."""

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from app.db import engine
from app.models import AIFeedback
from app.scheduler import purge_old_ai_feedback


def test_feedback_older_than_12_months_is_purged_and_recent_kept(demo):
    now = datetime.now(timezone.utc)
    with DbSession(engine) as db:
        db.add_all([
            AIFeedback(shop_id=demo["shop_id"], kind="down", question_masked="old", created_at=now - timedelta(days=400)),
            AIFeedback(shop_id=demo["shop_id"], kind="down", question_masked="new", created_at=now - timedelta(days=30)),
        ])
        db.commit()
        removed = purge_old_ai_feedback(db, now)
        left = db.scalars(select(AIFeedback.question_masked)).all()
    assert removed == 1
    assert list(left) == ["new"]


def test_deleting_the_account_removes_its_feedback(client, demo):
    from app.accounts import delete_user_account
    from app.models import Shop, User
    with DbSession(engine) as db:
        user = User(email="owner-fb@example.invalid")
        db.add(user)
        db.flush()
        shop = Shop(name="Магазин владельца", timezone="Asia/Almaty", owner_user_id=user.id)
        db.add(shop)
        db.flush()
        shop_id = shop.id
        db.add(AIFeedback(shop_id=shop_id, kind="flag", question_masked="q"))
        db.commit()
        delete_user_account(db, db.get(User, user.id))
    with DbSession(engine) as db:
        assert db.scalar(select(func.count()).select_from(AIFeedback).where(AIFeedback.shop_id == shop_id)) == 0
