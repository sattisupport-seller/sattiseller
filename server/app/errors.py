"""Ошибки API в формате docs/spec.md, раздел 5.1: {"error": {"code", "message", "error_id"}}.

Сообщения — на языке пользователя (Accept-Language: ru | kk), без stacktrace.
"""

import uuid

from fastapi import Request
from fastapi.responses import JSONResponse

MESSAGES: dict[str, dict[str, str]] = {
    "unauthorized": {"ru": "Нужно войти в аккаунт.", "kk": "Аккаунтқа кіру керек."},
    "token_expired": {"ru": "Сессия истекла. Войдите снова.", "kk": "Сессия мерзімі өтті. Қайта кіріңіз."},
    "forbidden": {"ru": "Нет доступа к этому магазину.", "kk": "Бұл дүкенге қол жеткізу жоқ."},
    "not_found": {"ru": "Не найдено.", "kk": "Табылмады."},
    "validation": {"ru": "Проверьте введённые данные.", "kk": "Енгізілген деректерді тексеріңіз."},
    "rate_limited": {"ru": "Слишком много запросов. Попробуйте позже.", "kk": "Тым көп сұраныс. Кейінірек қайталаңыз."},
    "code_invalid": {"ru": "Неверный код.", "kk": "Код қате."},
    "code_expired": {"ru": "Код устарел. Отправьте новый.", "kk": "Код мерзімі өтті. Жаңасын жіберіңіз."},
    "ai_consent_required": {
        "ru": "Сначала разрешите передачу данных ИИ-сервису.",
        "kk": "Алдымен ЖИ-қызметке деректерді беруге рұқсат беріңіз.",
    },
    "ai_limit": {"ru": "На сегодня вопросы закончились. Новые — завтра.", "kk": "Бүгінгі сұрақтар аяқталды."},
    "import_bad_file": {"ru": "Не удалось прочитать файл.", "kk": "Файлды оқу мүмкін болмады."},
    "import_too_large": {
        "ru": "Файл больше 5 МБ. Сохраните его без картинок и попробуйте снова.",
        "kk": "Файл 5 МБ-дан үлкен. Суретсіз сақтап, қайта көріңіз.",
    },
}


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str | None = None):
        self.status = status
        self.code = code
        self.message = message
        super().__init__(code)


def localized(code: str, lang: str = "ru") -> str:
    entry = MESSAGES.get(code, MESSAGES["validation"])
    return entry.get(lang, entry["ru"])


def pick_lang(accept_language: str | None) -> str:
    if accept_language and accept_language.lower().startswith("kk"):
        return "kk"
    return "ru"


async def api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
    lang = pick_lang(request.headers.get("accept-language"))
    message = exc.message or localized(exc.code, lang)
    return JSONResponse(
        status_code=exc.status,
        content={"error": {"code": exc.code, "message": message, "error_id": uuid.uuid4().hex[:12]}},
    )
