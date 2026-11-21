"""3.8: оценка качества помощника на фиксированном наборе вопросов (мок, без внешней модели).

Набор — tests/ai_eval_set.json. Для каждого вопроса проверяется: ответ содержит хотя бы одну из ожидаемых фраз,
в ответе нет переноса строки, нет адресов и телефонов, а отказы (что нельзя менять и чьи данные не хранятся) —
отказы. Порог: не меньше 90% вопросов. Отчёт пишется в tests/ai_eval_report.json (в git не попадает).
"""

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session as DbSession

from app import ai as ai_service
from app.db import engine
from app.models import Shop

SET = json.loads((Path(__file__).parent / "ai_eval_set.json").read_text(encoding="utf-8"))
SET_B = json.loads((Path(__file__).parent / "ai_eval_set_b.json").read_text(encoding="utf-8"))
REPORT = Path(__file__).parent / "ai_eval_report.json"
THRESHOLD = 0.9
# Границы слова для «ул.» и «улица»: без них «вернул.» ложно считалось адресом (исправлено после круга 2).
PII = re.compile(r"\+?\d[\d\s()-]{8,}\d|@[\w.]+|\bул\.|\bулица\b", re.IGNORECASE)


# Синонимы одного понятия. Добавлены после круга 1 по итогам разбора: ожидаемый корень «закупк» не совпадает
# с правильным словом «закупочной», а «не храню» — с правильным «не хранятся». Таблица одна для всех выборок.
SYNONYMS = {
    "закупк": ["закупоч"],
    "не храню": ["не хранятся"],
}


def _term_found(term: str, answer: str) -> bool:
    forms = [term.lower(), *SYNONYMS.get(term.lower(), [])]
    return any(form in answer for form in forms)


def _check(item: dict, answer: str) -> tuple[bool, str]:
    if "\n" in answer:
        return False, "перенос строки в ответе"
    if PII.search(answer):
        return False, "похоже на контакт или адрес"
    if not any(_term_found(term, answer.lower()) for term in item["any"]):
        return False, "нет ожидаемой фразы"
    return True, ""


def run_eval(shop_id: str, items=None) -> dict:
    results = []
    with DbSession(engine) as db:
        shop = db.get(Shop, shop_id)
        now = datetime.now(timezone.utc)
        for item in (items or SET):
            answer = ai_service.ask(db, shop, item["question"], None, None, now=now)["renderedAnswer"]
            ok, why = _check(item, answer)
            results.append({"id": item["id"], "ok": ok, "why": why, "answer": answer})
        db.rollback()
    passed = sum(r["ok"] for r in results)
    return {"total": len(results), "passed": passed, "ratio": round(passed / len(results), 3), "results": results}


def test_assistant_quality_meets_threshold(demo):
    report = run_eval(demo["shop_id"])
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    failed = [r for r in report["results"] if not r["ok"]]
    assert report["ratio"] >= THRESHOLD, f"{report['passed']} из {report['total']}: {failed}"


def test_second_set_is_reported_without_tuning(demo):
    """Независимая выборка (ai_eval_set_b.json): результат фиксируется в отчёте, мок под неё не подгоняется."""
    report = run_eval(demo["shop_id"], SET_B)
    (Path(__file__).parent / "ai_eval_report_b.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    assert report["total"] >= 30
