"""3.8 на живой модели: выборки A, B, C. Тратит деньги, поэтому запускается только с SATTI_AI_EVAL_LIVE=1.

Итоговый критерий (ТЗ, решение владельца): выборка C — ответы не меньше 90%, отказы — 100%.
Выборка B — только отчёт, помечена как не независимая (мок и правила её видели). A — отчёт.
Отчёт пишется в tests/ai_eval_live_report.json (в git не попадает). Стоимость — по учёту бюджета.
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from app import ai as ai_service
from app.config import settings
from app.db import engine
from app.models import AIUsageEvent, Shop
from tests.test_ai_eval import _check

pytestmark = pytest.mark.skipif(os.environ.get("SATTI_AI_EVAL_LIVE") != "1",
                                reason="живой прогон тратит деньги: нужен SATTI_AI_EVAL_LIVE=1")

HERE = Path(__file__).parent
SETS = [("A", "ai_eval_set.json"), ("B", "ai_eval_set_b.json"), ("C", "ai_eval_set_c.json"), ("D", "ai_eval_set_d.json")]
OFFICIAL = "D"  # слепая выборка, написанная до круга 2; остальные — для сравнения
THRESHOLD = 0.9


def _load(name: str) -> list[dict]:
    return json.loads((HERE / name).read_text(encoding="utf-8"))


def _spent_micro(db: DbSession) -> int:
    return int(db.scalar(select(func.coalesce(func.sum(AIUsageEvent.cost_micro_usd), 0))) or 0)


def test_live_eval_on_sets_a_b_c(demo, monkeypatch):
    assert settings.anthropic_api_key, "нет ключа ANTHROPIC_API_KEY в server/.env"
    monkeypatch.setattr(settings, "ai_live", True)
    report: dict = {"model": settings.ai_model, "sets": {}}
    with DbSession(engine) as db:
        shop = db.get(Shop, demo["shop_id"])
        spent_before = _spent_micro(db)
        for label, fname in SETS:
            rows = []
            for item in _load(fname):
                out = ai_service.ask(db, shop, item["question"], None, None,
                                     now=datetime.now(timezone.utc), debug=True)
                ok, why = _check(item, out["renderedAnswer"])
                rows.append({"id": item["id"], "kind": item.get("kind", "answer"), "ok": ok, "why": why,
                             "liveUsed": out["liveUsed"], "liveError": out.get("liveError"),
                             "toolCalls": out["toolCalls"], "answer": out["renderedAnswer"]})
            db.commit()
            answers = [r for r in rows if r["kind"] != "refusal"]
            refusals = [r for r in rows if r["kind"] == "refusal"]
            report["sets"][label] = {
                "independent": label not in ("A", "B", "C"),  # A, B, C открыты и использовались для разбора
                "total": len(rows),
                "answers_ok": sum(r["ok"] for r in answers), "answers_total": len(answers),
                "refusals_ok": sum(r["ok"] for r in refusals), "refusals_total": len(refusals),
                "live_used": sum(r["liveUsed"] for r in rows),
                "results": rows,
            }
        spent_micro = _spent_micro(db) - spent_before
    report["cost_usd"] = round(spent_micro / 1_000_000, 6)
    (HERE / "ai_eval_live_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    d = report["sets"][OFFICIAL]
    assert d["answers_ok"] / d["answers_total"] >= THRESHOLD, (
        f"{OFFICIAL}: ответы {d['answers_ok']} из {d['answers_total']}")
    assert d["refusals_ok"] == d["refusals_total"], f"{OFFICIAL}: отказы {d['refusals_ok']} из {d['refusals_total']}"
