"""Публичные страницы (ТЗ 2.1, 13.2 и 24): политика конфиденциальности, условия, веб-форма удаления аккаунта.

Тексты берутся из docs/legal (черновики для юриста, помечены как черновики). Страницы — без внешних скриптов.
Удаление через веб-форму: код на почту, затем удаление — та же логика, что в приложении (раздел 9.3).
Ответы формы одинаковы, есть ли аккаунт, — чтобы не раскрывать регистрацию.
"""

from __future__ import annotations

import html
from datetime import datetime, timedelta, timezone
from pathlib import Path

import markdown
from fastapi import APIRouter, BackgroundTasks, Depends, Form, Request
from fastapi.responses import FileResponse, HTMLResponse
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from .config import settings
from .db import get_session
from .mailer import MailError, send_code_email
from .errors import pick_lang
from .accounts import delete_user_account
from .models import AuthCode, User
from .ratelimit import allow, client_ip
from .security import hash_code, new_code

LEGAL_DIR = Path(__file__).resolve().parent / "legal"  # копия текстов из docs/legal, входит в пакет
STATIC_DIR = Path(__file__).resolve().parent / "static"
PAGES = {
    "privacy": ("Политика конфиденциальности", "privacy-policy-draft.md"),
    "terms": ("Пользовательское соглашение", "terms-draft.md"),
}

router = APIRouter(include_in_schema=False)

_STYLE = """
:root { color-scheme: light dark; --fg:#111827; --bg:#ffffff; --muted:#6b7280; --accent:#4F46E5; --warn:#B45309; }
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) { --fg:#F3F4F6; --bg:#0F172A; --muted:#9CA3AF; --accent:#8B93FF; --warn:#FBBF24; } }
:root[data-theme="dark"] { --fg:#F3F4F6; --bg:#0F172A; --muted:#9CA3AF; --accent:#8B93FF; --warn:#FBBF24; }
body { margin:0; background:var(--bg); color:var(--fg); font:16px/1.6 -apple-system, system-ui, "Segoe UI", Roboto, sans-serif; }
main { max-width: 760px; margin: 0 auto; padding: 16px; }
h1 { font-size: 26px; } h2 { font-size: 20px; margin-top: 28px; } h3 { font-size: 17px; }
table { border-collapse: collapse; width: 100%; margin: 12px 0; font-size: 15px; }
th, td { border: 1px solid var(--muted); padding: 6px 8px; text-align: left; vertical-align: top; }
blockquote { margin: 16px 0; padding: 10px 14px; border-left: 4px solid var(--warn); color: var(--warn); }
a { color: var(--accent); }
input { font: inherit; padding: 12px; width: 100%; box-sizing: border-box; border-radius: 10px; border: 1px solid var(--muted); background: transparent; color: var(--fg); }
button { font: inherit; padding: 12px 16px; border: 0; border-radius: 12px; background: var(--accent); color: #fff; width: 100%; }
.note { color: var(--muted); font-size: 14px; }
"""


def _page(title: str, body: str) -> HTMLResponse:
    doc = f"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)} — Satti Seller</title>
<style>{_STYLE}</style></head>
<body><main>{body}</main></body></html>"""
    return HTMLResponse(doc)


def _legal(slug: str) -> HTMLResponse:
    title, filename = PAGES[slug]
    path = LEGAL_DIR / filename
    if not path.exists():
        return _page(title, "<h1>Текст готовится</h1>")
    text = path.read_text(encoding="utf-8")
    # имя оператора — из SATTI_OWNER_NAME (до регистрации ИП); в продакшене без него сервер не стартует
    text = text.replace("{OWNER_NAME}", settings.owner_name or "Владелец приложения Satti Seller")
    # К-28: данные ИП — из переменных; подстановки сработают, когда юрист добавит их в тексты
    text = text.replace("{OWNER_IIN}", settings.owner_iin or "")
    text = text.replace("{OWNER_CITY}", settings.owner_city or "")
    text = text.replace("{SUPPORT_EMAIL}", settings.support_email or "")
    return _page(title, markdown.markdown(text, extensions=["tables"]))


@router.get("/support", response_class=HTMLResponse)
def support_page() -> HTMLResponse:
    """Страница поддержки (5.8). Адрес — из SATTI_SUPPORT_EMAIL; без адреса письмо не показывается."""
    if settings.support_email:
        email = html.escape(settings.support_email)
        contact = f'<p>Напишите нам: <a href="mailto:{email}">{email}</a>. Отвечаем в рабочие дни.</p>'
    else:
        contact = "<p>Адрес поддержки будет указан здесь перед публикацией приложения.</p>"
    faq = """
<h2>Частые вопросы</h2>
<p><b>Что делает Satti?</b> Считает прибыль по каждому товару после закупки, комиссии, доставки и налога, показывает товары в минус и объясняет, почему изменилась прибыль.</p>
<p><b>Это приложение Kaspi?</b> Нет. Satti — независимый сервис и не связан с Kaspi.kz.</p>
<p><b>Почему прибыль — «оценка»?</b> Она зависит от данных, которые вы ввели: закупки, ставок комиссии, налога. Если чего-то не хватает, Satti показывает это и не выдаёт оценку за точное число.</p>
<p><b>Как отменить подписку?</b> iPhone: Настройки → [ваше имя] → Подписки → Satti Seller → Отменить. Android: Google Play → Профиль → Платежи и подписки → Подписки → Satti Seller → Отменить.</p>
<p><b>Как удалить аккаунт?</b> В приложении: Профиль → Удалить аккаунт. Понадобится код из письма.</p>
"""
    links = '<p><a href="/privacy">Политика конфиденциальности</a> · <a href="/terms">Условия использования</a></p>'
    body = f"<h1>Поддержка</h1>{contact}{faq}{links}"
    return _page("Поддержка Satti Seller", body)


@router.get("/admin", response_class=HTMLResponse)
def admin_page() -> HTMLResponse:
    """Веб-страница панели поверх API /v1/admin. Данные отдаёт только API, и только владельцу с кодом 2FA."""
    return HTMLResponse((STATIC_DIR / "admin.html").read_text(encoding="utf-8"))


@router.get("/admin.js", include_in_schema=False)
def admin_script() -> FileResponse:
    """Скрипт панели вынесен из страницы (AUD-25): так политика CSP не разрешает встроенные скрипты."""
    return FileResponse(STATIC_DIR / "admin.js", media_type="application/javascript")


@router.get("/privacy", response_class=HTMLResponse)
def privacy_page() -> HTMLResponse:
    return _legal("privacy")


@router.get("/terms", response_class=HTMLResponse)
def terms_page() -> HTMLResponse:
    return _legal("terms")


_FORM = """<h1>Удаление аккаунта</h1>
<p class="note">Аккаунт и данные магазина будут удалены. Действие необратимо. Подписка при этом не отменяется автоматически:
отмените её в App Store или Google Play.</p>
<form method="post" action="/delete-account/start">
  <p><label>Email аккаунта<br><input name="email" type="email" required></label></p>
  <p><button type="submit">Прислать код на почту</button></p>
</form>"""


def _code_form(email: str) -> str:
    return f"""<h1>Введите код</h1>
<p class="note">Если аккаунт с адресом {html.escape(email)} существует, мы отправили на него код на 10 минут.</p>
<form method="post" action="/delete-account/confirm">
  <p><label>Email<br><input name="email" type="email" value="{html.escape(email)}" required></label></p>
  <p><label>Код из письма<br><input name="code" inputmode="numeric" maxlength="6" required></label></p>
  <p><button type="submit">Удалить аккаунт</button></p>
</form>"""


@router.get("/delete-account", response_class=HTMLResponse)
def delete_account_page() -> HTMLResponse:
    return _page("Удаление аккаунта", _FORM)


def _send_delete_code(email: str, code: str, lang: str) -> None:
    try:
        send_code_email(email, code, "delete", lang)
    except MailError:
        pass  # та же страница, что и без ошибки: не показываем, есть ли аккаунт


@router.post("/delete-account/start", response_class=HTMLResponse)
def delete_account_start(request: Request, background: BackgroundTasks, email: str = Form(...),
                         db: DbSession = Depends(get_session)) -> HTMLResponse:
    address = email.strip().lower()
    # аудит 27.11, L6: лимит и по адресу клиента; письмо — в фоне, время ответа не выдаёт, есть ли аккаунт
    if allow(f"webdelete-ip:{client_ip(request)}", 20, db=db) and allow(f"webdelete:{address}", 5, db=db):
        user = db.scalar(select(User).where(User.email == address))
        if user is not None:
            code = new_code()
            db.add(AuthCode(email=user.email, purpose="delete", user_id=user.id, code_hash=hash_code(user.email, code),
                            expires_at=datetime.now(timezone.utc) + timedelta(minutes=settings.code_ttl_minutes)))
            db.commit()
            background.add_task(_send_delete_code, user.email, code, pick_lang(request.headers.get("accept-language")))
    return _page("Введите код", _code_form(address))


@router.post("/delete-account/confirm", response_class=HTMLResponse)
def delete_account_confirm(email: str = Form(...), code: str = Form(...),
                           db: DbSession = Depends(get_session)) -> HTMLResponse:
    address = email.strip().lower()
    user = db.scalar(select(User).where(User.email == address))
    if user is None or not allow(f"webdelete-confirm:{address}", 10, db=db):
        return _page("Не удалось", "<h1>Код неверный или истёк</h1><p><a href='/delete-account'>Начать сначала</a></p>")
    from .accounts import check_delete_code

    if not check_delete_code(db, user, code):  # аудит 27.11, M1: после 5 неверных попыток код сгорает
        return _page("Не удалось", "<h1>Код неверный или истёк</h1><p><a href='/delete-account'>Начать сначала</a></p>")
    delete_user_account(db, user)
    return _page("Аккаунт удалён", "<h1>Аккаунт удалён</h1><p>Данные магазина удалены. Спасибо, что были с нами.</p>")


@router.get("/favicon.ico", include_in_schema=False)
def favicon() -> FileResponse:
    """Иконка вкладки для веб-страниц (QA: раньше отдавало 404)."""
    return FileResponse(STATIC_DIR / "favicon.png", media_type="image/png")
