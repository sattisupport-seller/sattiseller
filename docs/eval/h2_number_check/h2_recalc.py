"""Независимый пересчёт метрик из сырых строк демо-магазина (без импорта кода приложения).
Правила читаются из описания приложения: местное время магазина, статусы, распределение расходов, округление half-up."""
import json, re, sys
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
from decimal import Decimal, ROUND_HALF_UP

DUMP = "C:/Users/user/AppData/Local/Temp/claude/af86fe85628ce651/4b538c71-6f33-443b-b00b-30504987d818/scratchpad/h2_dump.json"
d = json.load(open(DUMP, encoding="utf-8"))
from datetime import timezone as _tz
TZ = _tz(timedelta(hours=5))  # Asia/Almaty: постоянное UTC+5 с 2024 года
SALE = {"completed", "returned", "partial_return"}
CANCEL = {"cancelled"}

def rhu(num, den):  # деление с округлением половины от нуля
    q = (Decimal(num) / Decimal(den)).quantize(Decimal(1), rounding=ROUND_HALF_UP)
    return int(q)

def apply_bp(amount, bp):
    return rhu(amount * bp, 10000)

def pday(s):
    if s is None:
        return None
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_tz.utc)
    return dt.astimezone(TZ).date()

def applicable(rows, day, key="effective_from"):
    rows = sorted(rows, key=lambda r: (r.get(key) is not None, r.get(key) or ""))
    ok = [r for r in rows if r.get(key) is None or date.fromisoformat(r[key]) <= day]
    return ok[-1] if ok else None

products = {p["id"]: p for p in d["products"]}
costs = {}
for v in d["cost_versions"]:
    costs.setdefault(v["product_id"], []).append(v)
presets = {}
for p in d["presets"]:
    presets.setdefault(p["category"], []).append(p)
taxes = d["tax_rates"]
orders = {o["id"]: o for o in d["orders"]}
items = {i["id"]: i for i in d["order_items"]}
returns_by_item = {}
for r in d["returns"]:
    returns_by_item.setdefault(r["item_id"], []).append(r)

facts = []  # одна запись на строку заказа
for it in d["order_items"]:
    o = orders[it["order_id"]]
    p = products.get(it["product_id"])
    if p is None:
        continue
    sale_day = pday(o["completed_at"]) if o["completed_at"] else None
    created_day = pday(o["created_at"])
    basis = sale_day or created_day
    cv = applicable(costs.get(p["id"], []), basis)
    landed_unit = None if cv is None else cv["purchase_minor"] + cv["delivery_to_warehouse_minor"] + cv["packaging_minor"] + cv["other_minor"]
    pr = applicable(presets.get(p["category"], []), basis)
    tr = applicable(taxes, basis)
    tax_bp = None if tr is None else tr["rate_bp"]
    rate = it["commission_rate_bp"] if it["commission_rate_bp"] is not None else (None if pr is None else pr["rate_bp"])
    qty, unit = it["qty"], it["unit_price_minor"]
    gross = unit * qty
    landed = None if landed_unit is None else landed_unit * qty
    commission = None if rate is None else apply_bp(gross, rate)
    delivery = it["buyer_delivery_minor"]
    tax = 0 if tax_bp is None else apply_bp(gross, tax_bp)
    profit = None
    if None not in (landed, commission, delivery):
        profit = gross - landed - commission - delivery - tax
    complete = profit is not None
    rets = []
    for r in returns_by_item.get(it["id"], []):
        rday = pday(r["confirmed_at"])
        rt = applicable(taxes, rday)
        tax_ret = 0 if (rt is None or r["refund_minor"] is None) else apply_bp(r["refund_minor"], rt["rate_bp"])
        known = all(r[k] is not None for k in ("refund_minor", "commission_returned_minor", "delivery_returned_minor", "reverse_delivery_minor"))
        delta = None
        if known:
            recovered = landed_unit * r["returned_qty"] if (r["goods_sellable"] and landed_unit is not None) else 0
            extra_delivery = r["reverse_delivery_minor"] - r["delivery_returned_minor"]
            delta = -r["refund_minor"] + recovered + r["commission_returned_minor"] + tax_ret - extra_delivery
        rets.append(dict(day=rday, refund=r["refund_minor"] or 0, delta=delta, returned_qty=r["returned_qty"]))
    facts.append(dict(name=p["name"].lower(), sku=p["sku"], purchase=(None if cv is None else cv["purchase_minor"]), order_id=o["id"], created_day=created_day, sale_day=sale_day, status=o["status"], qty=qty, gross=gross,
                      sale=(o["status"] in SALE), profit=profit, complete=complete, commission=commission or 0,
                      delivery=delivery or 0, landed=landed or 0, tax=tax, returns=rets, cancelled=(o["status"] in CANCEL),
                      order_sum=gross))

def period_metrics(a, b):
    m = dict(orders=0, orders_sum=0, cancelled=0, cancelled_sum=0, net_sales=0, net_complete=0, profit=0,
             gross_complete=0, commission=0, delivery=0, landed=0, tax=0, returns=0, refunds=0, refunds_c=0)
    order_sums = {}
    order_day = {}
    order_cancel = {}
    for f in facts:  # сумма заказа = сумма его позиций
        order_sums[f["order_id"]] = order_sums.get(f["order_id"], 0) + f["gross"]
        order_day[f["order_id"]] = f["created_day"]
        order_cancel[f["order_id"]] = f["cancelled"]
    for oid, day in order_day.items():  # учёт по заказам, не по позициям
        if a <= day <= b:
            m["orders"] += 1
            m["orders_sum"] += order_sums[oid]
            if order_cancel[oid]:
                m["cancelled"] += 1
                m["cancelled_sum"] += order_sums[oid]
    for f in facts:
        if f["sale"] and f["sale_day"] and a <= f["sale_day"] <= b:
            m["net_sales"] += f["gross"]
            if f["complete"]:
                m["net_complete"] += f["gross"]
                m["gross_complete"] += f["gross"]
                m["profit"] += f["profit"]
                m["commission"] += f["commission"]
                m["delivery"] += f["delivery"]
                m["landed"] += f["landed"]
                m["tax"] += f["tax"]
        for r in f["returns"]:
            if r["day"] and a <= r["day"] <= b:
                m["returns"] += 1
                m["refunds"] += r["refund"]
                if f["complete"]:
                    m["refunds_c"] += r["refund"]
                m["net_sales"] -= r["refund"]
                if f["complete"] and r["delta"] is not None:
                    m["profit"] += r["delta"]
                    m["net_complete"] -= r["refund"]
    m["avg_check"] = rhu(m["orders_sum"], m["orders"]) if m["orders"] else None
    m["margin_pct_1dec"] = round(m["profit"] * 100 / m["net_complete"], 1) if m["net_complete"] > 0 else None
    # расходы: распределение по дням, округление half-up по каждой записи
    ads = other = 0
    for e in d["expenses"]:
        ps, pe = date.fromisoformat(e["period_start"]), date.fromisoformat(e["period_end"])
        total = (pe - ps).days + 1
        os_, oe = max(ps, a), min(pe, b)
        if oe < os_ or total <= 0:
            continue
        share = rhu(e["amount_minor"] * ((oe - os_).days + 1), total)
        if e["kind"] == "ads":
            ads += share
        else:
            other += share
    m["ads"], m["other_expenses"] = ads, other
    return m

if __name__ == "__main__":
    a, b = date.fromisoformat(sys.argv[1]), date.fromisoformat(sys.argv[2])
    print(json.dumps(period_metrics(a, b), ensure_ascii=False))
