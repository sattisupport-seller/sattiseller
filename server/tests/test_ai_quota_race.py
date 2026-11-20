"""AUD-17: параллельные вопросы не превышают дневной лимит ИИ."""

from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient

from app.main import app


def test_parallel_questions_do_not_exceed_daily_limit(client, demo):
    consent = client.post("/v1/ai/consent", json={"granted": True}, headers=demo["headers"])
    assert consent.status_code == 200, consent.text
    url = f"/v1/shops/{demo['shop_id']}/ai/ask"

    def ask(i: int) -> int:
        # у каждого потока свой клиент: так запросы действительно идут параллельно
        with TestClient(app) as c:
            return c.post(url, json={"question": f"Вопрос номер {i}?"}, headers=demo["headers"]).status_code

    with ThreadPoolExecutor(max_workers=8) as pool:
        codes = list(pool.map(ask, range(40)))

    assert codes.count(200) == 30, codes
    assert codes.count(429) == 10, codes
    assert set(codes) <= {200, 429}, codes
