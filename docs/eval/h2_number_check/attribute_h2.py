"""Привязка каждого числа ответа H2 к метрике, названной рядом (ближайшее слово слева), и сверка именно с ней."""
import json, re, importlib.util
from datetime import date, timedelta
spec = importlib.util.spec_from_file_location('v', 'verify_h2.py')
src = open('verify_h2.py', encoding='utf-8').read().split("ROOT = ")[0]
ns = {}
exec(compile(src, 'verify_h2.py', 'exec'), ns)
periods, metric_values, find_numbers, product_near = ns['periods'], ns['metric_values'], ns['find_numbers'], ns['product_near']

KEYS = [  # (регулярка, метрика, подпись) — порядок важен
    (r"(прочие расходы|прочих расходов|прочее|прочих|басқа шығыстар|өзге шығындар|прочие)", "other_expenses", "прочие расходы"),
    (r"(чистые продажи|чистых продаж|таза сатылым|таза түсім|чистые)", "net_complete", "чистые продажи"),
    (r"(маржа|маржи|маржинал|маржу)", "margin_pct", "маржа"),
    (r"(средн\w* чек|орташа чек|средн\w* чека)", "avg_check", "средний чек"),
    (r"(комисси|комиссия)", "commission", "комиссия"),
    (r"(доставк|жеткіз)", "delivery", "доставка"),
    (r"(реклам|жарнама)", "ads", "реклама"),
    (r"(отмен\w*|отмены|отменено)", "cancelled_sum", "отмены"),
    (r"(возврат\w*|қайтар\w*)", "refunds_c", "возвраты"),
    (r"(прибыл\w*|пайда\w*|табыс\w*)", "profit", "прибыль"),
    (r"(выручк\w*|сумм\w*|сатылым сомасы|жалпы сомасы)", "orders_sum", "сумма заказов"),
    (r"(заказ\w*|тапсырыс\w*)", "orders", "заказы"),
]
LABEL_KEYS = [(re.compile(rx, re.I), key, name) for rx, key, name in KEYS]

RIGHT = [(re.compile(r"^\s*(заказ\w*|тапсырыс\w*)", re.I), "orders", "заказы"),
         (re.compile(r"^\s*(шт\.?|штук\w*|дана|дана\w*)", re.I), "returns", "штуки/возвраты"),
         (re.compile(r"^\s*(₸|тенге)", re.I), None, "сумма")]
def attribute(text, pos, end=None):
    after = text[end if end is not None else pos:][:18]
    if re.match(r"^\s*(заказ|тапсырыс|заказа|заказов)", after, re.I):  # «44 заказа» — число относится к заказам
        return ("orders", "заказы")
    if re.match(r"^\s*(шт)", after, re.I):  # «2 шт.» — штуки возвратов в ответах H2 (возвраты)
        left_ret = re.search(r"(возврат\w*|қайтар\w*)", text[max(0, pos - 40):pos].lower())
        if left_ret:
            return ("refunds_c" if False else "returns", "возвраты, штуки")
    left = text[max(0, pos - 45):pos].lower()
    matches = []
    for rx, key, name in LABEL_KEYS:
        for m in rx.finditer(left):
            matches.append((m.end(), key, name))
    if not matches:
        for rx, key, name in RIGHT:
            if key and rx.match(after):
                return (key, name)
        return None
    best = max(matches, key=lambda x: x[0])
    # «на сумму» рядом с возвратом/отменой — это сумма возвратов/отмен, а не выручка
    if best[1] == "orders_sum":
        spec = [m for m in matches if m[1] in ("refunds_c", "cancelled_sum", "returns", "cancelled") and best[0] - m[0] <= 25]
        if spec:
            best = max(spec, key=lambda x: x[0])
    return (best[1], best[2])

ROOT = "C:/Users/user/Desktop/satti-seller/server/tests/ai_eval_live_runs/claude-haiku-5-5_{}/H2.jsonl"
res = {"верно": 0, "неверно": 0, "не привязано": 0, "товар/пропуск": 0}
wrong_items = []; unbound = []; subst = []
for run in ["h2r1", "h2r2", "h2r3"]:
    for l in open(ROOT.format(run), encoding="utf-8"):
        r = json.loads(l)
        if r["kind"] == "refusal" or not r.get("answer"): continue
        text = r["answer"]
        per = periods(text)
        if not per:
            continue
        mvs = [metric_values(a, b) for a, b in per]
        deriv = {}
        for i in range(len(mvs)):
            for j in range(len(mvs)):
                if i == j: continue
                for k, x in mvs[i].items():
                    if k in mvs[j] and isinstance(x, float) and mvs[j][k]:
                        deriv.setdefault(k, []).append(x - mvs[j][k])
                        deriv.setdefault(k + '_pct', []).append((x - mvs[j][k]) * 100 / abs(mvs[j][k]))
                    elif k in mvs[j] and not isinstance(x, float) and mvs[j][k]:
                        deriv.setdefault(k, []).append(x - mvs[j][k])
                        deriv.setdefault(k + '_pct', []).append((x - mvs[j][k]) * 100 / abs(mvs[j][k]))
        for n in find_numbers(text):
            if product_near(text, n["pos"]):
                res["товар/пропуск"] += 1; continue
            key = attribute(text, n["pos"], n["pos"] + len(n["raw"]))
            if key is None:
                res["не привязано"] += 1; unbound.append((run, r["id"], n["raw"], text[max(0,n["pos"]-40):n["pos"]+5])); continue
            mkey, mname = key
            vals = [mv.get(mkey) for mv in mvs] + deriv.get(mkey, []) + deriv.get(mkey + '_pct', [])
            ok = any(v is not None and (abs(n["val"] - v) < 0.51) for v in vals)
            if not ok and mkey == 'margin':
                ok = any(v is not None and abs(n["val"] - v) < 0.051 for v in [mv.get('margin') for mv in mvs])
            if ok:
                res["верно"] += 1; continue
            # подмена? совпало с другой метрикой того же периода
            other = None
            for mv in mvs:
                for k, x in mv.items():
                    if k != mkey and x is not None and abs(n["val"] - x) < 0.51:
                        other = k
            res["неверно"] += 1
            wrong_items.append((run, r["id"], n["raw"], mname, mkey, other, text[max(0,n["pos"]-50):n["pos"]+15].replace("\n"," ")))
            if other: subst.append(wrong_items[-1])
print(res)
print("ПОДМЕНА (число совпало с другой метрикой):", len(subst))
for w in subst: print(" ", w)
print("НЕВЕРНО (не совпало ни с чем):", len(wrong_items)-len(subst))
for w in wrong_items:
    if w not in subst: print(" ", w)
print("НЕ ПРИВЯЗАНО:", len(unbound))
for u in unbound[:30]: print(" ", u)
json.dump(dict(res=res, wrong=wrong_items, unbound=unbound), open('attr_out.json','w',encoding='utf-8'), ensure_ascii=False, indent=1)
