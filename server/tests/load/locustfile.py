"""Нагрузка (QA этап 8): демо-сессия на пользователя, затем основные экраны.

Запуск (сервер уже поднят на тестовой базе):
  locust -f tests/load/locustfile.py --host http://127.0.0.1:8100 --headless -u 50 -r 10 -t 60s --csv qa-load
Не запускать против боевого сервера.
"""

import uuid

from locust import HttpUser, between, task


class SellerUser(HttpUser):
    wait_time = between(0.5, 2)

    def on_start(self):
        with self.client.post("/v1/demo/session", headers={"X-Device-Id": f"load-{uuid.uuid4().hex}"},
                              name="demo session", catch_response=True) as r:
            if r.status_code != 200:
                r.failure(f"demo session {r.status_code}")
                self.stop()
                return
            r.success()
            body = r.json()
        self.shop = body["shop_id"]
        self.headers = {"Authorization": f"Bearer {body['access_token']}"}

    @task(3)
    def overview(self):
        self.client.get(f"/v1/shops/{self.shop}/overview?period=7d", headers=self.headers, name="overview")

    @task(2)
    def products(self):
        self.client.get(f"/v1/shops/{self.shop}/products?period=30d", headers=self.headers, name="products")

    @task(2)
    def orders(self):
        self.client.get(f"/v1/shops/{self.shop}/orders?period=30d&limit=20", headers=self.headers, name="orders")

    @task(1)
    def profit(self):
        self.client.get(f"/v1/shops/{self.shop}/profit-breakdown?period=30d", headers=self.headers, name="profit")
