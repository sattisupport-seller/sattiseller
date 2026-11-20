"""Нагрузочная проверка API (docs/qa, этап 6). Запускать ТОЛЬКО на тестовом сервере.

Пример: python scripts/load_check.py --base http://127.0.0.1:8090/v1 --users 20 --requests 15
Скрипт создаёт демо-сессии (тестовые данные), бьёт по основным эндпоинтам и печатает p50/p95/max и ошибки.
"""

import argparse
import json
import statistics
import threading
import time
import urllib.error
import urllib.request

PATHS = [
    "/shops/{shop}/overview?period=7d",
    "/shops/{shop}/profit-breakdown?period=30d",
    "/shops/{shop}/products?period=30d",
    "/shops/{shop}/orders?period=30d&limit=20",
]


def demo_session(base: str, device: str) -> tuple[str, str]:
    req = urllib.request.Request(base + "/demo/session", data=b"{}", method="POST",
                                 headers={"Content-Type": "application/json", "X-Device-Id": device})
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = json.loads(resp.read())
    return body["access_token"], body["shop_id"]


def call(url: str, token: str) -> tuple[float, int]:
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            resp.read()
            return (time.perf_counter() - started) * 1000, resp.status
    except urllib.error.HTTPError as exc:
        return (time.perf_counter() - started) * 1000, exc.code
    except Exception:  # noqa: BLE001 — сетевая ошибка считается отказом
        return (time.perf_counter() - started) * 1000, 0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", required=True)
    parser.add_argument("--users", type=int, default=20)
    parser.add_argument("--requests", type=int, default=15)
    args = parser.parse_args()

    sessions = [demo_session(args.base, f"load-device-{i:04d}") for i in range(args.users)]
    latencies: list[float] = []
    statuses: dict[int, int] = {}
    lock = threading.Lock()

    def worker(token: str, shop: str) -> None:
        for n in range(args.requests):
            path = PATHS[n % len(PATHS)].format(shop=shop)
            ms, status = call(args.base + path, token)
            with lock:
                latencies.append(ms)
                statuses[status] = statuses.get(status, 0) + 1

    threads = [threading.Thread(target=worker, args=(tok, shop)) for tok, shop in sessions]
    started = time.perf_counter()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    wall = time.perf_counter() - started

    latencies.sort()
    p50 = statistics.median(latencies)
    p95 = latencies[int(len(latencies) * 0.95) - 1]
    ok = statuses.get(200, 0)
    print(json.dumps({
        "users": args.users, "requests_total": len(latencies), "wall_seconds": round(wall, 2),
        "throughput_rps": round(len(latencies) / wall, 1), "p50_ms": round(p50, 1), "p95_ms": round(p95, 1),
        "max_ms": round(latencies[-1], 1), "status_counts": statuses, "http_200": ok,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
