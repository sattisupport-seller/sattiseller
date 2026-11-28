"""К-37: сводка прогона реального магазина — по журналу сервера и тестовой базе. Только чтение.

  python scripts/kaspi_watch.py --log <журнал сервера> --db <kaspi_test.db>

Печатает: подключение и прогресс загрузки, заказы по статусам и датам, запросы к Kaspi (метод, коды ответов),
запросы НЕ на чтение (должно быть 0), поля и статусы, которые прислал Kaspi, незнакомые статусы, пропущенные записи.
Данные покупателей и токен не печатаются (их нет ни в журнале, ни в выводе).
"""

from __future__ import annotations

import argparse
import re
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timezone

KASPI_REQ = re.compile(r"HTTP Request: (\w+) https://kaspi\.kz(\S*) \"HTTP/1\.1 (\d{3})")


def log_summary(path: str) -> None:
    text = open(path, encoding="utf-8", errors="replace").read()
    reqs = KASPI_REQ.findall(text)
    methods = Counter(m for m, _p, _c in reqs)
    codes = Counter(c for _m, _p, c in reqs)
    kinds = Counter(re.sub(r"/[A-Za-z0-9_-]{6,}", "/{id}", p.split("?")[0]) for _m, p, _c in reqs)
    print(f"Запросы к Kaspi: всего {len(reqs)}; методы {dict(methods)}; ответы {dict(sorted(codes.items()))}")
    writes = [(m, p) for m, p, _c in reqs if m != "GET"]
    print(f"  НЕ на чтение (должно быть 0): {len(writes)}" + (f" — {writes[:3]}" if writes else ""))
    for k, n in kinds.most_common(6):
        print(f"  {n:6} {k}")
    for line in re.findall(r"kaspi observed .*", text)[-1:]:
        print("Поля и статусы Kaspi (последняя синхронизация):")
        print("  " + line[:1500])
    unknown = Counter(re.findall(r"kaspi unknown status '([^']*)'", text))
    print(f"Незнакомые статусы: {dict(unknown) or 'нет'}")
    skipped = re.findall(r"kaspi (\w+) skipped: id=\S+ (\w+)", text)
    print(f"Пропущенные записи: {len(skipped)}" + (f" — {Counter(skipped).most_common(3)}" if skipped else ""))
    errors = [ln for ln in text.splitlines() if " ERROR " in ln or "Traceback" in ln]
    print(f"Ошибки сервера: {len(errors)}" + (f" — {errors[-1][:200]}" if errors else ""))


def db_summary(path: str) -> None:
    c = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    rows = c.execute("select shop_id, status, seller_id, connected_at, last_sync_at, load_done, load_total, "
                     "backfill_done, last_error from kaspi_connections").fetchall()
    if not rows:
        print("Подключений Kaspi пока нет.")
        return
    for shop_id, status, seller, connected, last_sync, done, total, bf, err in rows:
        print(f"Подключение: магазин {shop_id[:8]}, ID продавца {seller}, статус {status}")
        print(f"  подключено {connected}; последняя синхронизация {last_sync}")
        print(f"  загружено {done} из ~{total}; догрузка 90 дней {'закончена' if bf else 'идёт'}")
        if err:
            print(f"  последняя ошибка: {err}")
        by_status = dict(c.execute("select status, count(*) from orders where shop_id=? group by status", (shop_id,)))
        first, last = c.execute("select min(created_at), max(created_at) from orders where shop_id=?", (shop_id,)).fetchone()
        print(f"  заказы: {sum(by_status.values())} {by_status}; создание с {first} по {last}")
        items, qty = c.execute("select count(*), coalesce(sum(qty),0) from order_items where shop_id=?", (shop_id,)).fetchone()
        products = c.execute("select count(*) from products where shop_id=?", (shop_id,)).fetchone()[0]
        delivery = c.execute("select count(*), coalesce(sum(buyer_delivery_minor),0) from order_items "
                             "where shop_id=? and buyer_delivery_minor > 0", (shop_id,)).fetchone()
        credit = c.execute("select count(*) from order_items where shop_id=? and commission_rate_bp is not null",
                           (shop_id,)).fetchone()[0]
        handed = c.execute("select count(*) from orders where shop_id=? and in_delivery_at is not null", (shop_id,)).fetchone()[0]
        print(f"  позиций {items} ({qty} шт.), товаров {products}; с доставкой продавца {delivery[0]} "
              f"(на {delivery[1] / 100:,.0f} ₸ с НДС)".replace(",", " ")
              + f"; в рассрочку {credit}; переданы в Kaspi Доставку {handed}")


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--log", required=True)
    p.add_argument("--db", required=True)
    a = p.parse_args(argv)
    print(f"Сводка прогона на {datetime.now(timezone.utc).astimezone().strftime('%d.%m %H:%M:%S')}")
    db_summary(a.db)
    log_summary(a.log)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
