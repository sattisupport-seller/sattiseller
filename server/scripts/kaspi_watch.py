"""К-37: сводка прогона реального магазина — по журналу сервера и тестовой базе. Только чтение.

  python scripts/kaspi_watch.py --log <журнал сервера> --db <kaspi_test.db>

Печатает: подключение и прогресс загрузки, заказы по статусам и датам, запросы к Kaspi (метод, коды ответов),
запросы НЕ на чтение (должно быть 0), поля и статусы, которые прислал Kaspi, незнакомые статусы, пропущенные записи.
Данные покупателей и токен не печатаются (их нет ни в журнале, ни в выводе).
Ещё (К-37 п.3 и п.6): время до первых цифр и до полной загрузки 90 дней — по журналу; список «что сверить
с кабинетом Kaspi» — 5 заказов (номер, дата по времени магазина, статус, сумма товаров) и итог за 14 дней.
"""

from __future__ import annotations

import argparse
import re
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

KASPI_REQ = re.compile(r"HTTP Request: (\w+) https://kaspi\.kz(\S*) \"HTTP/1\.1 (\d{3})")
LOG_TIME = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")
STATUS_RU = {  # как в кабинете Kaspi, приблизительно: исход заказа
    "pending": "новый",
    "in_progress": "в работе",
    "completed": "выдан",
    "cancelled": "отменён",
    "returned": "возврат",
}


def _tenge(minor: int) -> str:
    return f"{minor / 100:,.0f}".replace(",", " ")


def _fmt_delta(sec: float) -> str:
    sec = int(sec)
    return f"{sec // 60} мин {sec % 60:02d} с" if sec >= 60 else f"{sec} с"


def load_timing(text: str) -> dict[str, float | None]:
    """Секунды от первого запроса заказов к Kaspi до первых цифр («kaspi observed») и до конца догрузки."""

    def first_time(pred) -> datetime | None:
        for line in text.splitlines():
            m = LOG_TIME.match(line)
            if m and pred(line):
                return datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")
        return None

    start = first_time(lambda ln: "HTTP Request: GET https://kaspi.kz" in ln and "/orders" in ln)
    first = first_time(lambda ln: "kaspi observed" in ln)
    done = first_time(lambda ln: "kaspi backfill done" in ln)
    if start is None:
        return {"first_numbers": None, "full_load": None}
    return {
        "first_numbers": (first - start).total_seconds() if first else None,
        "full_load": (done - start).total_seconds() if done else None,
    }


def print_timing(text: str) -> None:
    t = load_timing(text)
    if t["first_numbers"] is None and t["full_load"] is None:
        print("Время загрузки: в журнале ещё нет запросов заказов к Kaspi или первых цифр.")
        return
    first = _fmt_delta(t["first_numbers"]) if t["first_numbers"] is not None else "ещё нет"
    full = _fmt_delta(t["full_load"]) if t["full_load"] is not None else "ещё идёт"
    print(f"Время загрузки: до первых цифр {first}; до полной загрузки 90 дней {full}")


def _parse_db_time(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(str(value)).replace(tzinfo=timezone.utc)  # в базе — UTC без пояса


def check_list(c: sqlite3.Connection, shop_id: str, now: datetime | None = None) -> list[str]:
    """Что сверить с кабинетом Kaspi: 5 разных заказов и итог за 14 дней. Без данных покупателей."""
    row = c.execute("select timezone from shops where id=?", (shop_id,)).fetchone()
    tz = ZoneInfo(row[0] if row and row[0] else "Asia/Almaty")
    now = now or datetime.now(timezone.utc)
    since = now - timedelta(days=14)
    orders = c.execute(
        "select o.id, o.number, o.status, o.created_at, coalesce(sum(i.qty * i.unit_price_minor), 0) "
        "from orders o left join order_items i on i.order_id = o.id where o.shop_id=? "
        "group by o.id order by o.created_at desc", (shop_id,)).fetchall()
    recent = [o for o in orders if (_parse_db_time(o[3]) or now) >= since]
    if not recent:
        return ["Заказов за 14 дней нет — сверять нечего."]
    picked: list[tuple] = []

    def take(o):
        if o and o not in picked and len(picked) < 5:
            picked.append(o)

    take(recent[0])  # самый новый
    for st in ("completed", "cancelled", "returned", "in_progress"):
        take(next((o for o in recent if o[2] == st), None))  # по одному каждого исхода
    take(max(recent, key=lambda o: o[4]))  # самый крупный
    take(recent[-1])  # самый ранний за 14 дней
    for o in recent:
        take(o)

    lines = ["Сверить с кабинетом Kaspi (Заказы → поиск по номеру):"]
    for _id, number, status, created, total in picked:
        local = _parse_db_time(created).astimezone(tz).strftime("%d.%m.%Y %H:%M")
        lines.append(f"  № {number}: {local}, {STATUS_RU.get(status, status)}, товары на {_tenge(total)} ₸")
    by_status = Counter(o[2] for o in recent)
    sums = Counter()
    for o in recent:
        sums[o[2]] += o[4]
    lines.append(f"Итог за 14 дней (с {since.astimezone(tz):%d.%m}): заказов {len(recent)}; " + "; ".join(
        f"{STATUS_RU.get(s, s)} {n} на {_tenge(sums[s])} ₸"
        for s, n in sorted(by_status.items(), key=lambda kv: -kv[1])))
    lines.append("  Сумма — цена товаров × количество, без доставки. В кабинете сравнить число и сумму по каждому статусу.")
    return lines


def log_summary(path: str) -> None:
    text = open(path, encoding="utf-8", errors="replace").read()
    reqs = KASPI_REQ.findall(text)
    methods = Counter(m for m, _p, _c in reqs)
    codes = Counter(c for _m, _p, c in reqs)
    kinds = Counter(re.sub(r"/[A-Za-z0-9_-]{6,}", "/{id}", p.split("?")[0]) for _m, p, _c in reqs)
    print_timing(text)
    print(f"Запросы к Kaspi: всего {len(reqs)}; методы {dict(methods)}; ответы {dict(sorted(codes.items()))}")
    writes = [(m, p) for m, p, _c in reqs if m != "GET"]
    print(f"  НЕ на чтение (должно быть 0): {len(writes)}" + (f" — {writes[:3]}" if writes else ""))
    for k, n in kinds.most_common(6):
        print(f"  {n:6} {k}")
    for line in re.findall(r"kaspi observed .*", text)[-1:]:
        print("Поля и статусы Kaspi (последняя синхронизация):")
        print("  " + line[:1500])
    shapes: dict[str, str] = {}
    for kind, shape in re.findall(r"kaspi shape shop=\S+ (\S+) (.*)", text):
        shapes[kind] = shape  # последняя по каждому виду запроса
    if shapes:
        print("Структура ответов Kaspi (поля и типы, без значений) — для KASPI_TEST §9:")
        for kind, shape in sorted(shapes.items()):
            print(f"  {kind}: {shape[:1500]}")
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
        for line in check_list(c, shop_id):
            print(line)


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
