"""AUD-08: после удаления аккаунта не остаётся записей, которые ведут к человеку."""

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from app.billing import RetentionEvent, Subscription
from app.db import engine
from app.models import AIUsageEvent, AuthCode, Shop, User
from app.social_auth import SocialIdentity
from tests.conftest import confirm_age, login


def _last_code(email: str) -> str:
    from app.config import settings

    files = sorted(settings.outbox_dir.glob("*.eml"), key=lambda p: p.stat().st_mtime)
    for f in reversed(files):
        body = f.read_text(encoding="utf-8")
        if f"To: {email}" in body and "удаления" in body:
            return body.split("Ваш код: ")[1].split()[0]
    raise AssertionError("письмо с кодом удаления не найдено")


def _count(db, model, *conds) -> int:
    q = select(func.count()).select_from(model)
    for c in conds:
        q = q.where(c)
    return db.scalar(q) or 0


def test_account_deletion_leaves_no_personal_rows(client):
    email = f"audit-{uuid.uuid4().hex[:8]}@example.invalid"
    tokens = login(client, email)
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    confirm_age(client, headers)
    shop = client.post("/v1/shops", json={"name": "Удаление"}, headers=headers).json()
    client.post("/v1/ai/consent", json={"granted": True}, headers=headers)
    assert client.post(f"/v1/shops/{shop['id']}/ai/ask", json={"question": "Сколько заказов?"},
                       headers=headers).status_code == 200
    user_id = tokens["user"]["id"]

    # запись входа через провайдера, которую создаёт social_auth при первом входе
    with DbSession(engine) as db:
        db.add(SocialIdentity(provider="google", subject=f"sub-{uuid.uuid4().hex}", user_id=user_id))
        # подписка и событие хранения магазина: их тоже должны убрать
        db.add(Subscription(shop_id=shop["id"], state="trial", access_until=datetime.now(timezone.utc) + timedelta(days=14),
                            store="test"))
        db.add(RetentionEvent(shop_id=shop["id"], kind="letter_0"))
        db.commit()

    assert client.post("/v1/me/deletion/start", headers=headers).status_code == 202
    code = _last_code(email)
    assert client.post("/v1/me/deletion/confirm", headers=headers, json={"code": code}).status_code == 200

    with DbSession(engine) as db:
        assert _count(db, User, User.id == user_id) == 0
        assert _count(db, AuthCode, AuthCode.email == email) == 0
        assert _count(db, AuthCode, AuthCode.user_id == user_id) == 0
        assert _count(db, SocialIdentity, SocialIdentity.user_id == user_id) == 0
        assert _count(db, AIUsageEvent, AIUsageEvent.user_id == user_id) == 0
        assert _count(db, Shop, Shop.owner_user_id == user_id) == 0
        assert _count(db, Subscription, Subscription.shop_id == shop["id"]) == 0
        assert _count(db, RetentionEvent, RetentionEvent.shop_id == shop["id"]) == 0


def test_deletion_sends_confirmation_letter(client):
    """3.6: после удаления — письмо-подтверждение на адрес аккаунта."""
    from app.config import settings

    email = f"bye-{uuid.uuid4().hex[:8]}@example.invalid"
    tokens = login(client, email)
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    assert client.post("/v1/me/deletion/start", headers=headers).status_code == 202
    assert client.post("/v1/me/deletion/confirm", headers=headers, json={"code": _last_code(email)}).status_code == 200
    letters = [f.read_text(encoding="utf-8") for f in settings.outbox_dir.glob("*.eml")]
    assert any(f"To: {email}" in t and "Аккаунт Satti удалён" in t for t in letters)
