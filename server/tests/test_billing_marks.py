"""AUD-16: отметка пробного периода уникальна; гонка двух запросов не даёт второй пробный период."""

import uuid

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DbSession

from app import billing
from app.billing import BillingMark
from app.db import engine
from app.device_trust import DeviceVerdict
from app.errors import ApiError
from app.models import KaspiConnection, Shop
from tests.conftest import confirm_age, login


def test_duplicate_mark_is_refused_by_database(client):
    key = billing._hash("user", "dup@example.invalid")
    with DbSession(engine) as db:
        db.add(BillingMark(kind="user", key_hash=key))
        db.commit()
    with DbSession(engine) as db:
        db.add(BillingMark(kind="user", key_hash=key))
        with pytest.raises(IntegrityError):
            db.commit()


def test_parallel_trial_request_cannot_create_second_trial(client, monkeypatch):
    email = f"race-{uuid.uuid4().hex[:8]}@example.invalid"
    tokens = login(client, email)
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    confirm_age(client, headers)
    shop_a = client.post("/v1/shops", json={"name": "A"}, headers=headers).json()["id"]
    shop_b = client.post("/v1/shops", json={"name": "B"}, headers=headers).json()["id"]

    ok = DeviceVerdict(available=True, trial_used=False)
    with DbSession(engine) as db:
        for sid, seller in ((shop_a, "RACE-A"), (shop_b, "RACE-B")):
            db.add(KaspiConnection(shop_id=sid, seller_id=seller, token_enc="x", price_key=uuid.uuid4().hex))
        db.commit()
    with DbSession(engine) as db:
        billing.start_trial(db, db.get(Shop, shop_a), email, ok)
    # второй запрос «прошёл проверку» одновременно с первым: проверка отвечает «можно»
    monkeypatch.setattr(billing, "trial_eligible", lambda *a, **k: True)
    with DbSession(engine) as db:
        with pytest.raises(ApiError) as exc:
            billing.start_trial(db, db.get(Shop, shop_b), email, ok)
    assert exc.value.status == 409
    assert exc.value.code == "trial_used"
