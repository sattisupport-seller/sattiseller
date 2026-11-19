# Satti Seller

Мобильное приложение для продавцов Kaspi (iPhone и Android): прибыль по каждому товару, заказы, недостающие данные и ИИ-помощник. Документация — в `docs/`, правила работы — в `CLAUDE.md`, план задач — `docs/spec.md`, раздел 16.

## Структура

```
server/   API на FastAPI (расчёты, данные, ИИ)
mobile/   приложение на Expo (Expo Router, TypeScript)
docs/     ТЗ: overview, spec, design, owner, ADR, макеты
```

## Сервер

```bash
cd server
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt   # Windows
.venv/Scripts/python.exe -m pytest                             # тесты, включая золотой набор
.venv/Scripts/python.exe -m uvicorn app.main:app --reload      # http://127.0.0.1:8000/v1/docs
```

## Приложение

```bash
cd mobile
npm install
npx tsc --noEmit        # typecheck
npx expo-doctor         # диагностика зависимостей
npx expo start          # dev-сервер; открыть в Expo Go или в development build
```

## Статус

- Задача 0: решение записано в `docs/adr/0002-mobile-and-api.md`.
- Задача 1 (частично): API с `/v1/health`, `/v1/app/config`, OpenAPI; ядро расчётов с золотым набором.
- Задача 2 (частично): каркас Expo Router, пять вкладок, токены светлой и тёмной темы, Inter, заготовки ru/kk.
- Остальные задачи — по плану в `docs/spec.md`.
