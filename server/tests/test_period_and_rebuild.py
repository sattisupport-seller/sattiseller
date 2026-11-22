"""3.8 (решения владельца 22.11): период распознаётся кодом (ru, kk, транслит); неверный живой ответ пересобирается
из инструментов и не уходит пользователю как текст сбоя."""

from app import ai as ai_service
from tests.test_ai_live import _ask, _reply, _text, _tool, live  # noqa: F401  (фикстура live)


def test_period_is_recognized_in_ru_kk_and_translit():
    cases = {
        "кеше жеткізуге қанша шығын кетті": "yesterday",
        "вчера сколько доставка": "yesterday",
        "keshe kanşa şyǵyn": "yesterday",
        "бүгін қанша табыс": "today",
        "осы апта қанша пайда": "7d",
        "эта неделя прибыль": "7d",
        "өткен ай пайда": "previous_month",
        "прошлый месяц продажи": "previous_month",
        "соңғы 14 күн пайда": "14d",
        "последние 30 дней прибыль": "30d",
        "за 3 месяца прибыль": "90d",
    }
    for q, expected in cases.items():
        assert ai_service.resolve_period(q) == expected, q


def test_unclear_period_is_not_guessed():
    assert ai_service.resolve_period("сколько продаж") is None  # период не назван — модель уточнит


def test_known_period_is_passed_to_model_so_it_does_not_ask(demo, live):
    live["script"] = [_reply([_tool("get_profit_summary", {"period": "yesterday"}, uid="p1")]),
                      _reply([_text("Кеше {F1} кезеңінде пайда {F2}.")])]  # вопрос на казахском — ответ на казахском
    out, _ = _ask(demo["shop_id"], "кеше жеткізуге қанша шығын кетті")
    first = live["requests"][0]["messages"][0]["content"]
    assert "(Период вопроса: вчера.)" in first
    assert out["liveUsed"] is True


def test_invalid_live_answer_is_rebuilt_from_tools_not_failure_text(demo, live):
    """Шаблон с подстановкой без вызова инструментов: пользователю уходит пересобранный из данных ответ."""
    bad = _reply([_text("Ответ: {F1} рублей.")])  # подстановка без вызова инструментов; повтор тоже неверный
    live["script"] = [bad, bad]
    out, _ = _ask(demo["shop_id"], "как удалить товар из списка")
    assert "Не удалось проверить" not in out["renderedAnswer"]
    assert "{F" not in out["renderedAnswer"]
    assert out["liveUsed"] is False  # ответ собран мок-правилами из данных магазина
