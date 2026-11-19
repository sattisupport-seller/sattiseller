"""ИИ-помощник (docs/spec.md, раздел 8).

Поток: проверка вопроса и лимита → план инструментов (только чтение, не больше 3) → факты с id (F1, F2, …)
→ шаблон ответа без цифр с плейсхолдерами → проверка шаблона → подстановка значений сервером.

Провайдер по умолчанию — MockProvider: правила разбора и шаблоны, без внешней модели. Шаблон не содержит
ни одной цифры вне плейсхолдеров; числа, даты, названия товаров и уверенность формирует сервер.
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from .config import settings
from .errors import ApiError
from .models import AIConversation, AIFeedback, AITurn, AIUsageEvent, Shop
from .money import format_tenge, round_half_up_div
from .periods import Period, resolve
from .reports import (
    ItemFact,
    ShopData,
    build_facts,
    explain_profit_change,
    load_shop,
    metrics_for,
    missing_costs,
    product_stats,
)

TOOL_LIMIT = 3
PLACEHOLDER = re.compile(r"\{(F\d+)\}")
DIGIT = re.compile(r"\d")
KK_LETTERS = set("әғқңөұүһі")
PHONE_RE = re.compile(r"\+?\d[\d\s\-()]{8,}\d")
MONTHS_RU = ["янв.", "февр.", "мар.", "апр.", "мая", "июн.", "июл.", "авг.", "сент.", "окт.", "нояб.", "дек."]
# Человекочитаемые подписи фактов для блока «Основания» (ТЗ, раздел 8.5).
FACT_LABELS = {
    "period_now": "Период",
    "period_prev": "Сравниваемый период",
    "period_days": "Период",
    "period": "Период",
    "period_label": "Период",
    "change": "Изменение прибыли",
    "change_pct": "Изменение, %",
    "top_name": "Главный товар",
    "units_prev": "Продажи раньше",
    "units_now": "Продажи сейчас",
    "nocost_count": "Товаров без закупки",
    "minus_count": "Товаров в минус",
    "orders": "Заказы",
    "profit": "Прибыль",
    "name": "Товар",
    "days": "Период",
}
SAFE_TEXT = "Не удалось сформировать ответ. Попробуйте переформулировать вопрос."


@dataclass
class Fact:
    id: str
    label: str
    kind: str  # money | orders | products | units | percent | text
    value: object


@dataclass
class Plan:
    template: str = ""
    facts: list[Fact] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    suggested: list[dict] = field(default_factory=list)
    coverage_inputs: list[int] = field(default_factory=list)
    lang: str = "ru"
    period: Period | None = None
    compare: Period | None = None


class Tools:
    """Инструменты только для чтения. Больше TOOL_LIMIT вызовов не выполняются."""

    def __init__(self, data: ShopData, facts: list[ItemFact], now: datetime):
        self.data = data
        self.facts = facts
        self.now = now
        self.calls = 0

    def _take(self) -> None:
        if self.calls >= TOOL_LIMIT:
            raise RuntimeError("tool limit exceeded")
        self.calls += 1

    def period(self, name: str) -> Period:
        return resolve(name, self.data.shop.timezone, self.now)

    def profit_summary(self, period: Period):
        self._take()
        return metrics_for(self.facts, self.data.orders, self.data.tz, period)

    def orders_count(self, period: Period) -> int:
        return self.profit_summary(period).orders_count

    def top_products(self, period: Period, order: str, limit: int) -> list:
        self._take()
        rows = [s for s in product_stats(self.data, self.facts, period).values() if s.profit is not None]
        rows.sort(key=lambda s: s.profit, reverse=(order == "desc"))
        return rows[:limit]

    def product_profit(self, sku: str, period: Period):
        self._take()
        for s in product_stats(self.data, self.facts, period).values():
            if s.product.sku.lower() == sku.lower():
                return s
        return None

    def missing_costs(self) -> list[dict]:
        self._take()
        return missing_costs(self.data)

    def explain(self, a: Period, b: Period) -> dict:
        self._take()
        return explain_profit_change(self.data, self.facts, a, b)


# ---------- форматирование значений ----------

def _fmt_period(p: Period) -> str:
    if p.start == p.end:
        return f"{p.start.day} {MONTHS_RU[p.start.month - 1]}"
    if p.start.month == p.end.month:
        return f"{p.start.day}–{p.end.day} {MONTHS_RU[p.end.month - 1]}"
    return f"{p.start.day} {MONTHS_RU[p.start.month - 1]} – {p.end.day} {MONTHS_RU[p.end.month - 1]}"


def _plural(n: int, one: str, few: str, many: str) -> str:
    n10, n100 = n % 10, n % 100
    if n10 == 1 and n100 != 11:
        return one
    if 2 <= n10 <= 4 and not 12 <= n100 <= 14:
        return few
    return many


def render_value(fact: Fact, lang: str = "ru") -> str:
    v = fact.value
    if fact.kind == "money":
        return format_tenge(int(v))
    if fact.kind == "orders":
        if lang == "kk":
            return f"{v} тапсырыс"
        return f"{v} {_plural(int(v), 'заказ', 'заказа', 'заказов')}"
    if fact.kind == "products":
        return f"{v} {_plural(int(v), 'товар', 'товара', 'товаров')}"
    if fact.kind == "units":
        return f"{v} шт."
    if fact.kind == "percent":
        bp = int(v)
        sign = "−" if bp < 0 else ""
        tenths = round_half_up_div(abs(bp), 10)
        return f"{sign}{tenths // 10},{tenths % 10}%"
    return str(v)


def _mk(facts: list[Fact], label: str, kind: str, value) -> str:
    fid = f"F{len(facts) + 1}"
    facts.append(Fact(fid, label, kind, value))
    return "{" + fid + "}"


def _pct_bp(prev: int, change: int) -> int:
    if prev == 0:
        return 0
    return round_half_up_div(change * 10_000, abs(prev))


# ---------- провайдер (правила) ----------

class MockProvider:
    """Разбор вопроса правилами и шаблоны ответов. Заменяется живой моделью после выбора поставщика."""

    def plan(self, question: str, tools: Tools, data: ShopData) -> Plan:
        q = question.lower()
        lang = "kk" if any(ch in KK_LETTERS for ch in q) else "ru"
        plan = Plan(lang=lang)
        facts: list[Fact] = []

        if re.search(r"поставь|измени|установи|смени|бағасын", q):
            plan.template = ("Изменять цены и остатки я не могу: помощник только показывает данные магазина. "
                             "Цену меняют в кабинете Kaspi.")
            return self._done(plan, facts)
        if re.search(r"телефон|адрес покупател|имя покупател|номер покупател", q):
            plan.template = ("Данных покупателей в приложении нет: телефоны, адреса и имена не хранятся "
                             "и не показываются.")
            return self._done(plan, facts)
        if re.search(r"конкурент", q):
            plan.template = ("Данных о ценах конкурентов в приложении нет. Могу ответить о прибыли, "
                             "заказах и товарах вашего магазина.")
            return self._done(plan, facts)

        if re.search(r"почему.*(упала|снизил|сниз)|(упала|снизил\w*) прибыл|прибыль\w* (упала|снизил)", q):
            return self._profit_change(plan, facts, tools, data)

        if re.search(r"в минус", q):
            period = tools.period("30d")
            plan.period = period
            negative = [r for r in tools.top_products(period, "asc", 5) if r.profit < 0]
            plan.coverage_inputs = [tools.profit_summary(period).coverage_bp]
            days_label = _mk(facts, "period_days", "text", "30 дней")
            if not negative:
                plan.template = f"За {days_label} товаров в минус нет."
                return self._done(plan, facts)
            names = ", ".join(_mk(facts, f"minus_{i}", "text", r.product.name) for i, r in enumerate(negative[:3]))
            plan.template = (f"За {days_label} в минус продаются товары: {names}. Всего "
                             f"{_mk(facts, 'minus_count', 'products', len(negative))}.")
            plan.suggested = [{"type": "open_product", "entityId": negative[0].product.id, "label": "Открыть товар"}]
            return self._done(plan, facts)

        if re.search(r"нет закупк|без закупк|не заполнена закупк|без закупочн", q):
            missing = tools.missing_costs()
            if not missing:
                plan.template = "Все товары с закупочной ценой."
                return self._done(plan, facts)
            names = ", ".join(_mk(facts, f"nocost_{i}", "text", m["name"]) for i, m in enumerate(missing[:5]))
            plan.template = (f"Без закупочной цены {_mk(facts, 'nocost_count', 'products', len(missing))}"
                             f": {names}. Их прибыль не считается.")
            plan.missing = [f"У {len(missing)} товаров нет закупочной цены"]
            plan.suggested = [{"type": "open_product", "entityId": missing[0]["product_id"],
                               "label": "Заполнить закупку"}]
            return self._done(plan, facts)

        sku_match = re.search(r"\b(d\d{3})\b", question, re.IGNORECASE)
        if sku_match and re.search(r"прибыл|заработ|дал|сколько", q):
            return self._product_profit(plan, facts, tools, sku_match.group(1))

        if re.search(r"заказ|тапсырыс", q):
            if re.search(r"вчера|кеше", q):
                period, label = tools.period("yesterday"), "вчера"
            else:
                period, label = tools.period("7d"), "за последние 7 дней"
            plan.period = period
            n = tools.orders_count(period)
            plan.coverage_inputs = []
            if lang == "kk":
                if label == "вчера":
                    plan.template = f"Кеше {_mk(facts, 'orders', 'orders', n)} болды."
                else:
                    plan.template = f"Соңғы {_mk(facts, 'days', 'text', '7 күнде')} {_mk(facts, 'orders', 'orders', n)} болды."
            else:
                plan.template = (f"Заказов {_mk(facts, 'period_label', 'text', label)}: "
                                 f"{_mk(facts, 'orders', 'orders', n)}.")
            return self._done(plan, facts)

        if re.search(r"прошл\w* месяц", q) and re.search(r"заработ|прибыл", q):
            period = tools.period("previous_month")
            plan.period = period
            res = tools.profit_summary(period)
            plan.coverage_inputs = [res.coverage_bp]
            plan.template = (f"За {_mk(facts, 'period', 'text', _fmt_period(period))} прибыль по полным данным — "
                             f"{_mk(facts, 'profit', 'money', res.profit)}.")
            return self._done(plan, facts)

        plan.template = ("Пока отвечаю о продажах, прибыли, заказах и товарах. Например: «Почему упала прибыль?», "
                         "«Какие товары в минус?», «Сколько заказов вчера?».")
        return self._done(plan, facts)

    def _done(self, plan: Plan, facts: list[Fact]) -> Plan:
        plan.facts = facts
        return plan

    def _profit_change(self, plan: Plan, facts: list[Fact], tools: Tools, data: ShopData) -> Plan:
        now_p = tools.period("14d")
        prev_p = now_p.previous_equal()
        plan.period, plan.compare = now_p, prev_p
        res = tools.explain(prev_p, now_p)
        plan.coverage_inputs = [res["coverage_a_bp"], res["coverage_b_bp"]]
        change = res["change_minor"]
        period_now = _mk(facts, "period_now", "text", _fmt_period(now_p))
        if change < 0:
            pct = _mk(facts, "change_pct", "percent", _pct_bp(res["profit_a_minor"], change))
            plan.template = (f"Прибыль за {period_now} снизилась на {_mk(facts, 'change', 'money', -change)} "
                             f"({pct}) по сравнению с {_mk(facts, 'period_prev', 'text', _fmt_period(prev_p))}.")
        else:
            plan.template = (f"Прибыль за {period_now} выросла на {_mk(facts, 'change', 'money', change)} "
                             f"по сравнению с {_mk(facts, 'period_prev', 'text', _fmt_period(prev_p))}.")

        top = res["top_driver"]
        if top and top["effect_minor"] < 0:
            row = next(p for p in res["products"] if p["product_id"] == top["product_id"])
            if top["main_factor"] == "volume":
                plan.template += (
                    f" Главная причина — {_mk(facts, 'top_name', 'text', top['name'])}: продажи упали с "
                    f"{_mk(facts, 'units_prev', 'units', row['units_a'])} до "
                    f"{_mk(facts, 'units_now', 'units', row['units_b'])}."
                )
            else:
                plan.template += (f" Главная причина — {_mk(facts, 'top_name', 'text', top['name'])}: "
                                  f"изменилась экономика одной продажи.")
            plan.suggested = [{"type": "open_product", "entityId": top["product_id"], "label": "Открыть товар"}]

        no_cost = [s for s in data.products.values() if not data.versions.get(s.id)]
        if no_cost:
            plan.missing = [f"У {len(no_cost)} товаров нет закупочной цены — их прибыль не учтена"]
            plan.template += (f" {_mk(facts, 'nocost_count', 'products', len(no_cost))} без закупочной цены — "
                              f"их прибыль не учтена.")
        return self._done(plan, facts)

    def _product_profit(self, plan: Plan, facts: list[Fact], tools: Tools, sku: str) -> Plan:
        period = tools.period("30d")
        plan.period = period
        s = tools.product_profit(sku, period)
        if s is None:
            plan.template = "Такого артикула в магазине нет."
            return self._done(plan, facts)
        plan.coverage_inputs = [tools.profit_summary(period).coverage_bp]
        if not s.has_cost:
            plan.template = (f"Недостаточно данных: у товара {_mk(facts, 'name', 'text', s.product.name)} нет "
                             f"закупочной цены, поэтому прибыль не считается.")
            plan.missing = ["Нет закупочной цены"]
            plan.suggested = [{"type": "open_product", "entityId": s.product.id, "label": "Добавить закупку"}]
            return self._done(plan, facts)
        if s.profit is None:
            plan.template = (f"По товару {_mk(facts, 'name', 'text', s.product.name)} данных для точного расчёта "
                             f"пока не хватает.")
            plan.missing = ["Неполные данные по товару"]
            return self._done(plan, facts)
        plan.template = (f"Расчётная прибыль по товару {_mk(facts, 'name', 'text', s.product.name)} за "
                         f"{_mk(facts, 'period_days', 'text', '30 дней')} — "
                         f"{_mk(facts, 'profit', 'money', s.profit)}.")
        plan.suggested = [{"type": "open_product", "entityId": s.product.id, "label": "Открыть товар"}]
        return self._done(plan, facts)


# ---------- проверка и подстановка ----------

def validate_template(template: str, facts: list[Fact]) -> None:
    ids = {f.id for f in facts}
    for ph in PLACEHOLDER.findall(template):
        if ph not in ids:
            raise ValueError(f"нет факта {ph}")
    if DIGIT.search(PLACEHOLDER.sub("", template)):
        raise ValueError("в шаблоне есть цифры вне плейсхолдеров")


def render(template: str, facts: list[Fact], lang: str) -> str:
    by_id = {f.id: f for f in facts}
    text = PLACEHOLDER.sub(lambda m: render_value(by_id[m.group(1)], lang), template)
    # «нояб.» в конце предложения не даёт вторую точку
    return re.sub(r"\.\.(?!\.)", ".", text)


def confidence(plan: Plan, estimates: bool = False) -> tuple[str | None, str | None]:
    if plan.missing:
        return None, None
    if not plan.coverage_inputs:
        return "high", "Ответ не зависит от закупочных цен"
    worst = min(plan.coverage_inputs)
    if worst < 7000:
        level = "low"
    elif worst < 9500 or estimates:
        level = "medium"
    else:
        level = "high"
    return level, f"Покрытие {render_value(Fact('c', 'coverage', 'percent', worst))} чистых продаж"


# ---------- сервис ----------

def check_quota(db: DbSession, user_id: str | None, shop_id: str, now: datetime) -> int:
    start = datetime.combine(now.date(), datetime.min.time(), tzinfo=timezone.utc)
    if user_id:
        used = db.scalar(select(func.count()).select_from(AIUsageEvent).where(
            AIUsageEvent.user_id == user_id, AIUsageEvent.created_at >= start))
    else:
        used = db.scalar(select(func.count()).select_from(AIUsageEvent).where(
            AIUsageEvent.shop_id == shop_id, AIUsageEvent.created_at >= start))
    if used >= settings.ai_daily_limit:
        raise ApiError(429, "ai_limit")
    return settings.ai_daily_limit - used - 1


def ask(db: DbSession, shop: Shop, question: str, user_id: str | None, conversation_id: str | None,
        now: datetime | None = None, provider: MockProvider | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    text = (question or "").strip()
    if not text:
        raise ApiError(422, "validation", "Напишите вопрос.")
    if len(text) > settings.ai_max_question_length:
        raise ApiError(422, "validation", "Вопрос длиннее 500 символов.")

    conv = None
    if conversation_id:
        conv = db.get(AIConversation, conversation_id)
        if conv is None or conv.shop_id != shop.id:
            raise ApiError(404, "not_found")

    data = load_shop(db, shop)
    facts = build_facts(data)
    tools = Tools(data, facts, now)
    plan = (provider or MockProvider()).plan(text, tools, data)

    try:
        validate_template(plan.template, plan.facts)
    except ValueError:
        plan.template = SAFE_TEXT
        plan.facts = []
        plan.missing = []
        plan.suggested = []
        plan.coverage_inputs = []
        validate_template(plan.template, plan.facts)

    rendered = render(plan.template, plan.facts, plan.lang)
    level, reason = confidence(plan)
    snapshot_id = f"rs_{uuid.uuid4().hex[:12]}"
    answer = {
        "answerTemplate": plan.template,
        "renderedAnswer": rendered,
        "period": _period_json(plan.period),
        "comparisonPeriod": _period_json(plan.compare),
        "dataAsOf": now.astimezone(timezone.utc).isoformat(),
        "evidence": [{"factId": f.id, "label": FACT_LABELS.get(f.label, f.label), "kind": f.kind,
                      "value": f.value if isinstance(f.value, (int, str)) else str(f.value),
                      "text": render_value(f, plan.lang),
                      "snapshotId": snapshot_id} for f in plan.facts],
        "missingData": plan.missing,
        "suggestedActions": plan.suggested,
        "confidence": level,
        "confidenceReason": reason,
        "lang": plan.lang,
        "toolCalls": tools.calls,
    }

    if conv is None:
        conv = AIConversation(shop_id=shop.id, user_id=user_id, title=text[:60], created_at=now)
        db.add(conv)
        db.flush()
    turn = AITurn(conversation_id=conv.id, shop_id=shop.id, user_id=user_id, question=text,
                  answer_json=json.dumps(answer, ensure_ascii=False), created_at=now)
    db.add(turn)
    db.add(AIUsageEvent(user_id=user_id, shop_id=shop.id, created_at=now, tool_calls=tools.calls))
    db.flush()
    answer["turnId"] = turn.id
    answer["conversationId"] = conv.id
    return answer


def _period_json(p: Period | None) -> dict | None:
    if p is None:
        return None
    return {"from": p.start.isoformat(), "to": p.end.isoformat()}


# ---------- черновики ----------

def product_draft(facts_text: str, languages: str, photos: int) -> dict:
    facts_text = (facts_text or "").strip()
    if not facts_text:
        raise ApiError(422, "validation", "Опишите товар: материалы, размеры, комплектацию.")
    if len(facts_text) > 1000:
        raise ApiError(422, "validation", "Факты длиннее 1000 символов.")
    if photos > 5:
        raise ApiError(422, "validation", "Можно добавить не больше 5 фото.")

    lines = [ln.strip(" -•\t") for ln in re.split(r"[\n;]+", facts_text) if ln.strip()]
    base = lines[0][:60]
    titles = [base]
    if len(lines) > 1:
        titles.append(f"{base}, {lines[1]}"[:60])
    titles.append(f"{base} — {lines[-1]}"[:60] if len(lines) > 2 else f"{base} для дома"[:60])
    description = " ".join(ln if ln.endswith(".") else f"{ln}." for ln in lines)

    characteristics = [
        {"name": "Материал", "value": "Уточнить"},
        {"name": "Размеры", "value": "Уточнить"},
        {"name": "Комплектация", "value": "Уточнить"},
    ]
    for ln in lines:
        if ":" in ln:
            key, _, value = ln.partition(":")
            for row in characteristics:
                if row["name"].lower() == key.strip().lower() and value.strip():
                    row["value"] = value.strip()

    out = {
        "titles": titles,
        "description": description,
        "characteristics": characteristics,
        "warnings": ["Проверьте текст перед публикацией. Satti ничего не публикует в Kaspi."],
        "languages": languages,
        "photosUsed": photos,
    }
    _check_no_new_numbers(out, facts_text)
    return out


def _check_no_new_numbers(out: dict, source: str) -> None:
    allowed = set(re.findall(r"\d+(?:[.,]\d+)?", source))
    text = " ".join([out["description"], *out["titles"], *[c["value"] for c in out["characteristics"]]])
    for num in re.findall(r"\d+(?:[.,]\d+)?", text):
        if num not in allowed:
            raise ApiError(422, "validation", "В черновике появилось число, которого нет в фактах.")


def reply_draft(question: str, tone: str) -> dict:
    q = (question or "").strip()
    if not q:
        raise ApiError(422, "validation", "Вставьте вопрос покупателя.")
    if len(q) > 500:
        raise ApiError(422, "validation", "Вопрос длиннее 500 символов.")
    warnings = ["Отправьте ответ в Kaspi сами: приложение ничего не отправляет."]
    if PHONE_RE.search(q):
        warnings.insert(0, "В вопросе есть номер телефона. Не вставляйте его в ответ.")
    greeting = "Здравствуйте!" if tone == "polite" else "Здравствуйте."
    body = ("Спасибо за вопрос. Уточните, пожалуйста, что именно вас интересует, и мы подскажем."
            if tone == "polite" else "Уточните, что именно нужно, и ответим.")
    return {"reply": f"{greeting} {body}", "warnings": warnings}


def record_feedback(db: DbSession, shop: Shop, turn_id: str | None, kind: str, reason: str | None,
                    comment: str | None) -> AIFeedback:
    if kind not in ("up", "down", "flag"):
        raise ApiError(422, "validation")
    fb = AIFeedback(shop_id=shop.id, turn_id=turn_id, kind=kind, reason=reason,
                    comment=(comment or "")[:500] or None)
    db.add(fb)
    db.flush()
    return fb


def load_answer(turn: AITurn) -> dict:
    return json.loads(turn.answer_json)


__all__ = ["ask", "Tools", "MockProvider", "render", "validate_template", "product_draft", "reply_draft",
           "record_feedback", "check_quota", "load_answer", "date"]
