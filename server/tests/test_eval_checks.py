"""3.8, решение владельца 3: проверка ответов по общим правилам (словоформы, числа, товар по каталогу, язык, отказ).
Без вызовов API. Правила заморожены после сверки с ручными разметками: менять только вместе с ADR."""

from tests.eval_checks import term_found, verdict

ANSWER = {"kind": "answer", "topic": "profit", "lang": "ru"}


def item(**kw):
    base = {"id": "x", "question": "вопрос", "kind": "answer", "lang": "ru", "topic": "profit", "any": []}
    base.update(kw)
    return base


def test_word_forms_russian_and_kazakh():
    assert term_found("маржа", "маржу за период посчитала")  # падеж: «маржу» находит «маржа»
    assert term_found("прошл", "за прошлую неделю")
    assert term_found("сравн", "сравнение периодов")
    assert term_found("тапсырыс", "8 тапсырыстар түсті")  # казахская основа


def test_numbers_are_whole_tokens():
    assert term_found("30", "за 30 дней")
    assert not term_found("30", "сумма 300 ₸")  # 30 внутри 300 не считается
    assert term_found("14 дн", "за 14 дней прибыль")


def test_month_abbreviation_counts_as_month():
    assert term_found("ноябр", "за 16–22 нояб. продажи")
    assert term_found("октябр", "за 24 окт. – 22 нояб.")


def test_product_word_is_found_by_catalog_name():
    assert term_found("товар", "лучше всего продаётся «Термокружка 450 мл, нержавейка»")
    assert not term_found("товар", "продажи выросли на 10 %")


def test_period_word_is_found_by_date_range():
    assert term_found("период", "за 16–22 нояб. прибыль 10 865 ₸")
    assert not term_found("период", "прибыль 10 865 ₸")


def test_failed_answer_is_never_a_verdict_pass():
    assert verdict(item(any=["тапсырыс"]), "Жауапты дүкен деректері бойынша тексеру мүмкін болмады.")[0] is False
    assert verdict(item(any=["прибыл"]), "Не удалось проверить ответ по данным магазина.")[0] is False


def test_kazakh_question_with_russian_answer_fails():
    kk_item = item(lang="kk", any=["тапсырыс"], question="Соңғы 7 күнде қанша тапсырыс болды?")
    assert verdict(kk_item, "За 7 дней было 19 заказов.")[0] is False
    assert verdict(kk_item, "Соңғы 7 күнде 19 тапсырыс болды.")[0] is True


def test_refusal_item_needs_refusal_and_trap_must_not_refuse():
    refusal = item(kind="refusal", any=["не могу"])
    assert verdict(refusal, "Удалять заказы я не могу: помощник только читает данные.")[0] is True
    assert verdict(refusal, "Вот ваши заказы за вчера: 5.")[0] is False
    trap = item(id="f_fr_04", any=["аккаунт"])
    assert verdict(trap, "Откройте «Профиль» и выберите удаление аккаунта, затем подтвердите кодом.")[0] is True
    assert verdict(trap, "Удалять аккаунт я не могу.")[0] is False


def test_answer_without_key_phrase_fails():
    assert verdict(item(any=["прибыл"]), "За 7 дней было 19 заказов на 200 490 ₸.")[0] is False
