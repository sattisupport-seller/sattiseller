# Satti Seller

Мобильное приложение для продавцов Kaspi (iPhone и Android): прибыль по каждому товару, заказы, недостающие данные и ИИ-помощник.

Текущий статус — первая строка `docs/REPORT.md`; указания координатора — `docs/INBOX.md`; передача дел — `docs/HANDOFF.md`.

Документация: план запуска — `docs/LAUNCH_PLAN.md`, пошагово для владельца — `docs/LAUNCH.md`, эксплуатация — `docs/OPERATIONS.md`, решения и вопросы — `docs/PROPOSALS.md`, полный план — `docs/MASTER_PLAN.md`, правила работы — `CLAUDE.md`.

## Структура
```
server/   API на FastAPI + SQLAlchemy (расчёты, импорт, помощник, демо)
mobile/   приложение на Expo SDK 58 (Expo Router, TypeScript)
docs/     ТЗ, ADR, макеты, черновик текстов для магазинов
```

## Версия 2.1 (ТЗ)
- План и решения: `docs/spec-2.1.md` (раздел 18 — задачи 16–35), `docs/adr/0003-spec-2.1-decisions.md`.
- Прогресс по задачам: `docs/progress-2.1.md`.
- Зависимости ставятся без `--legacy-peer-deps`.

## Запуск на Windows (PowerShell)
```powershell
cd server
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pytest
cd ..\mobile
npm install
npm test
npm run typecheck
```
Секреты — переменными окружения или в `server/.env` (сервер читает его при запуске; переменные окружения главнее; файл в .gitignore). Ключи-файлы — в `server/data/secrets/` (в .gitignore). Значения не вставляются в чат и не попадают в коммиты.

## Сервер
```bash
cd server
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt   # Windows
.venv/Scripts/python.exe -m pytest                             # ~725 тестов, 5–10 минут; на PostgreSQL — SATTI_TEST_DATABASE_URL
.venv/Scripts/python.exe -m uvicorn app.main:app --port 8000   # документация: http://127.0.0.1:8000/v1/docs
.venv/Scripts/alembic.exe upgrade head                         # миграции (SQLite по умолчанию)
```
Переменные: `DATABASE_URL`, `SATTI_DATA_DIR`, `SATTI_OUTBOX_DIR` (письма и пуши в разработке пишутся в папку outbox), `SATTI_CORS_ORIGINS` (для веб-просмотра). Полный список с описаниями — `server/.env.example`.
Замер объёма на моке Kaspi (10 000 товаров, 5 000 заказов): `.venv/Scripts/python.exe scripts/volume_check.py`.

## Приложение
```bash
cd mobile
npm install
npm test                       # ~235 тестов: экраны, сценарии, клиент API
npm run typecheck
EXPO_PUBLIC_API_URL=http://192.168.0.10:8000/v1 npx expo start   # телефон в одной сети с компьютером
npx expo start --web --port 8081                                  # просмотр в браузере (для проверки)
```
На телефоне адрес сервера задаётся `EXPO_PUBLIC_API_URL`; в веб-просмотре токены хранятся в localStorage.

## Статус
Готовность по чек-листу `docs/LAUNCH_PLAN.md` — 72,7 % (27.11.2026, `docs/FINAL_REPORT.md`). Почти всё оставшееся ждёт владельца: аккаунты Apple и Google, сервер и домен в Казахстане, Firebase/APNs, почтовый сервис, тестовый магазин Kaspi, юрист.
- Сделано на моках: покупки App Store и Google Play (ADR 0012), вход Apple/Google, пуши, Kaspi (синхронизация, прайс, возвраты), удаление и деактивация аккаунта, админка владельца.
- Интерфейс только на русском (ADR 0010).

## Конфигурация продакшена (сервер)
Запуск с `SATTI_ENV=production` отказывает, если не задано следующее (проверка в `app/config.py`):
- `SATTI_BILLING_PEPPER`, `SATTI_TOTP_KEY` — свои значения, не по умолчанию;
- `SATTI_CORS_ORIGINS` без localhost; `SATTI_EMAIL_LOGIN` не включён;
- блокировка по подписке: `SATTI_BILLING_ENFORCED=1` или осознанно `SATTI_FREE_ACCESS=1` (бесплатная бета); `SATTI_BILLING_TEST_MODE` не включён;
- `SATTI_SCHEDULER=1` — иначе удаление данных по хранению не запускается;
- хотя бы один способ входа: `SATTI_GOOGLE_CLIENT_IDS` или `SATTI_APPLE_CLIENT_ID`.
Дополнительно: `SATTI_TRUSTED_PROXIES` — адреса доверенного обратного прокси (только для них учитываются `X-Forwarded-For`), `SATTI_DEMO_MAX`, `SATTI_DEMO_NEW_PER_IP_PER_HOUR`.

## Проверено (27.11.2026)
- Сервер: 725 тестов на SQLite; на PostgreSQL 16.6 — 723 и исправленный фаззинг (подробности — `docs/REPORT.md`, «Тесты»).
- Приложение: jest 235, `tsc` без ошибок.
- Миграции Alembic: SQLite и PostgreSQL — вверх, вниз, вверх; `alembic check` без расхождений.
- Фаззинг OpenAPI под демо и под аккаунтом; gitleaks по истории git — секретов нет; `npm audit` — только умеренные в инструментах тестов.
- `deploy.sh` и `watchdog.sh` — `bash -n` и shellcheck; Caddyfile — `caddy validate`.
- На реальном телефоне последняя сборка не проверялась: чек-лист — `docs/DEVICE_CHECKLIST.md`.
