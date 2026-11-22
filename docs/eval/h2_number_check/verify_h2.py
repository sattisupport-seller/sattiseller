"""Независимая сверка чисел в ответах H2 с сырыми данными демо-магазина (без вызова API)."""
import json, re, importlib.util
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
spec = importlib.util.spec_from_file_location('h', 'h2_recalc.py'); h = importlib.util.module_from_spec(spec); spec.loader.exec_module(h)

NOW = date(2026, 11, 22)
MON = {"янв": 1, "фев": 2, "февр": 2, "мар": 3, "март": 3, "апр": 4, "апрел": 4, "май": 5, "мая": 5, "июн": 6,
       "июл": 7, "авг": 8, "сент": 9, "окт": 10, "октябр": 10, "нояб": 11, "ноябр": 11, "дек": 12, "декабр": 12}
def mnum(w):
    for k in sorted(MON, key=len, reverse=True):
        if w.startswith(k): return MON[k]
SPAN_R = re.compile(r"(\d{1,2})\s*([а-яё]{3,})\.?\s*(?:[–\-—]|по)\s*(\d{1,2})\s*([а-яё]{3,})\.?")
SPAN_S = re.compile(r"(\d{1,2})\s*[–\-—]\s*(\d{1,2})\s+([а-яё]{3,})\.?")
SPAN_C = re.compile(r"с\s+(\d{1,2})\s*(?:[а-яё]{3,})?\.?\s+по\s+(\d{1,2})\s+([а-яё]{3,})")
WORDS = [
    (r"(вчера|кеше|кешке)", (NOW - timedelta(1), NOW - timedelta(1))),
    (r"(сегодня|бүгін)", (NOW, NOW)),
    (r"(7 дн|семь дн|7 күн|жеті күн|7 дней|за неделю|эту неделю|эта неделя)", (NOW - timedelta(6), NOW)),
    (r"(14 дн|14 дней|14 күн|2 недел)", (NOW - timedelta(13), NOW)),
    (r"(30 дн|30 дней|30 күн)", (NOW - timedelta(29), NOW)),
    (r"(90 дн|90 дней|3 месяц)", (NOW - timedelta(89), NOW)),
    (r"(этот месяц|этом месяце|этого месяца|осы ай)", (date(2026, 11, 1), NOW)),
    (r"(прошлый месяц|прошлом месяце|прошлого месяца|өткен ай)", (date(2026, 10, 1), date(2026, 10, 31))),
]
EXACT_MON = {"янв": 1, "января": 1, "фев": 2, "февраля": 2, "мар": 3, "марта": 3, "апр": 4, "апреля": 4,
             "мая": 5, "май": 5, "июн": 6, "июня": 6, "июл": 7, "июля": 7, "авг": 8, "августа": 8,
             "сент": 9, "сентября": 9, "окт": 10, "октября": 10, "нояб": 11, "ноября": 11, "дек": 12, "декабря": 12}
SINGLE = re.compile(r"(?<![\d–\-—])(\d{1,2})\s+(янв|января|фев|февраля|мар|марта|апр|апреля|мая|июн|июня|июл|июля|авг|августа|сент|сентября|окт|октября|нояб|ноября|дек|декабря)\.?(?![а-яё])")
def periods(text):
    t = text.lower(); out = []
    for m in SINGLE.finditer(t):
        d_ = date(2026, EXACT_MON[m.group(2)], int(m.group(1)))
        if (d_, d_) not in out: out.append((d_, d_))
    for m in SPAN_R.finditer(t):
        a, b = mnum(m.group(2)), mnum(m.group(4))
        if a and b: out.append((date(2026, a, int(m.group(1))), date(2026, b, int(m.group(3)))))
    for m in SPAN_S.finditer(t):
        a = mnum(m.group(3))
        if a: out.append((date(2026, a, int(m.group(1))), date(2026, a, int(m.group(2)))))
    for m in SPAN_C.finditer(t):
        a = mnum(m.group(3))
        if a: out.append((date(2026, a, int(m.group(1))), date(2026, a, int(m.group(2)))))
    for rx, p in WORDS:
        if re.search(rx, t) and p not in out: out.append(p)
    return out

def rhu(x): return int(Decimal(x).quantize(Decimal(1), rounding=ROUND_HALF_UP))

def metric_values(a, b):
    m = h.period_metrics(a, b); v = {}
    for k in ("orders", "cancelled", "returns"): v[k] = m[k]
    for k in ("orders_sum", "cancelled_sum", "net_sales", "net_complete", "profit", "commission", "delivery",
              "landed", "refunds_c", "ads", "other_expenses"):
        v[k] = m[k] / 100
    v["avg_check"] = m["avg_check"] / 100 if m["avg_check"] is not None else None
    v["margin_pct"] = m["margin_pct_1dec"]
    return {k: x for k, x in v.items() if x is not None}

def product_values(name_low, a, b):
    qty = profit = 0; purchase = None
    for f in h.facts:
        if f["name"] != name_low: continue
        if f["sale"] and f["sale_day"] and a <= f["sale_day"] <= b:
            qty += f["qty"]
            if f["complete"]: profit += f["profit"]
        for r in f["returns"]:
            if r["day"] and a <= r["day"] <= b and f["complete"] and r["delta"] is not None: profit += r["delta"]
        if f["purchase"] is not None: purchase = f["purchase"] / 100
    return {"qty": qty, "profit": profit / 100, "purchase": purchase}

NUM = re.compile(r"(?<![\d–\-—/])(\d{1,3}(?:[ \u00a0]\d{3})+|\d+)(?:[,.](\d+))?(?![\d–\-—/])")
UNIT_AFTER = re.compile(r"^\s*(мл|л\b|вт\b|мм\b|см\b|кг\b|г\b|деталей|детал|предмет|пр\.|см)", re.I)
DATE_AFTER = re.compile(r"^\s*(нояб|окт|авг|сент|янв|фев|мар|апр|май|мая|июн|июл|дек|қараша|қазан|қыркүйек|тамыз)", re.I)
PRODUCT_NAMES = sorted({f["name"] for f in h.facts}, key=len, reverse=True)

def find_numbers(text):
    out = []
    for m in NUM.finditer(text):
        raw = m.group(1).replace(" ", "").replace("\u00a0", "")
        dec = m.group(2)
        val = float(f"{raw}.{dec}") if dec else float(int(raw))
        after = text[m.end():m.end() + 14]
        before = text[max(0, m.start() - 14):m.start()].lower()
        if DATE_AFTER.match(after) or UNIT_AFTER.match(after): continue
        if re.match(r'^\s*(янв|января|фев|февраля|мар|марта|апр|апреля|мая|июн|июня|июл|июля|авг|августа|сент|сентября|окт|октября|нояб|ноября|дек|декабря)', after, re.I): continue
        if re.match(r"^\s*(дн|дней|день|дня|күн|күнде|недел|месяц|месяца|неделю|күн)", after, re.I): continue
        if re.search(r"с\s*$", before) or re.search(r"по\s*$", before): continue
        if re.search(r"(по|–|-|—|\d)\s*$", before) and not re.search(r"\d\s*$", before): pass
        pct = after.lstrip().startswith("%")
        out.append(dict(val=val, pct=pct, pos=m.start(), raw=m.group(0), ctx=text[max(0, m.start()-60):m.end()+30]))
    return out

def product_near(text, pos):
    """Товар, к которому относится число: ближайшее название ПЕРЕД числом без другого названия между ними;
    если перед числом названия нет — ближайшее после него (в пределах 60 символов)."""
    tl = text.lower()
    occ = []
    for name in PRODUCT_NAMES:
        nl = name.lower(); i = tl.find(nl)
        while i >= 0:
            occ.append((i, i + len(nl), nl)); i = tl.find(nl, i + 1)
    before = [o for o in occ if o[1] <= pos]
    if before:
        last = max(before, key=lambda o: o[1])
        between = [o for o in occ if o[0] >= last[1] and o[1] <= pos and o != last]
        if not between and pos - last[1] <= 90:
            return last[2]
    after = [o for o in occ if o[0] >= pos and o[0] - pos <= 60]
    if after:
        return min(after, key=lambda o: o[0])[2]
    return None

ROOT = "C:/Users/user/Desktop/satti-seller/server/tests/ai_eval_live_runs/claude-haiku-5-5_{}/H2.jsonl"
total = ok_cnt = 0; unmatched = []; skipped_no_period = []; product_checked = 0; prod_ok = 0
for run in ["h2r1", "h2r2", "h2r3"]:
    for l in open(ROOT.format(run), encoding="utf-8"):
        r = json.loads(l)
        if r["kind"] == "refusal" or not r.get("answer"): continue
        text = r["answer"]
        per = periods(text)
        mv = [metric_values(a, b) for a, b in per]
        for i in range(len(mv)):
            for j in range(len(mv)):
                if i == j: continue
                for k in list(mv[i].keys()):
                    if k in mv[j] and k not in ('margin_pct',) and isinstance(mv[i][k], float) or k in mv[j] and k in ('orders','cancelled','returns'):
                        dif = mv[i][k] - mv[j][k]
                        mv[i]['d_'+k] = dif
                        if mv[j][k]: mv[i]['p_'+k] = round(dif * 100 / abs(mv[j][k]), 1)
        for n in find_numbers(text):
            prod = product_near(text, n["pos"])
            if prod is not None:
                # число у товара: штуки, прибыль, закупка — по периоду ответа (или за сегодня)
                if not per: skipped_no_period.append((run, r["id"], n["raw"], "товар без периода")); continue
                cands = []
                for a, b in per:
                    pv = product_values(prod, a, b)
                    cands.extend(pv.values())
                product_checked += 1
                if any(c is not None and abs(n["val"] - c) < 0.51 for c in cands):
                    prod_ok += 1
                else:
                    unmatched.append((run, r["id"], n["raw"], "товар:" + prod[:20], n["ctx"][-70:]))
                continue
            if not per:
                skipped_no_period.append((run, r["id"], n["raw"], n["ctx"][-50:])); continue
            total += 1
            cands = [x for v in mv for x in v.values() if x is not None]
            if n["pct"]:
                if any(abs(n["val"] - c) < 0.051 for c in cands if isinstance(c, float) or True):
                    ok_cnt += 1; continue
            if any(abs(n["val"] - c) < 0.51 for c in cands):
                ok_cnt += 1
            else:
                unmatched.append((run, r["id"], n["raw"], "метрика", n["ctx"][-70:]))
print("metric numbers checked:", total, "matched:", ok_cnt, "unmatched:", len([u for u in unmatched if u[3]=='метрика']))
print("product numbers checked:", product_checked, "matched:", prod_ok, "unmatched:", len([u for u in unmatched if u[3].startswith('товар')]))
print("numbers skipped (no period/product context):", len(skipped_no_period))
json.dump(dict(unmatched=unmatched, skipped=skipped_no_period), open("verify_out.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
