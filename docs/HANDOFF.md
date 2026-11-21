# HANDOFF — 21.11.2026, после 1.19 (повторное согласие)
Ветка: qa/full-check · Последний коммит: e2d672e (план 1.11) + коммит 1.19 (см. git log)
Тесты: сервер 354 на SQLite (на PostgreSQL последний прогон был до 1.19 — 342), приложение 116, ruff чистый, tsc чистый, экспорт Android проходит
Сделано в этой сессии: 1.19 закрыт — повторное согласие: `/me` отдаёт `terms_consent_required`, экран `app/terms-consent.tsx`, редирект в `_layout.tsx`, `acceptTerms` в SessionProvider; тест `test_me_reports_consent_needed_after_new_version`
Текущий пункт: 1.16 (демо из шаблона INSERT SELECT; нагрузка 10/50/100 на PostgreSQL)
Следующий шаг: 1.16, затем 1.17 (10 000 заказов), 1.4 (после 3.6)
Незакоммичено: в mobile/ не наши правки от 21.11 (app.json, eas.json, package.json, package-lock.json: expo-updates, EAS channels, дубль RECORD_AUDIO) — не трогались и не коммитились, решение владельца нужно
Проверка: .expo/types/router.d.ts пересоздан через `expo start` (gitignore) — без него tsc не знает маршрут /terms-consent
Падает: ничего известного; один тест на SQLite нестабилен (1 падение из 5 прогонов в 1.15, имя не найдено)
Открыто: 1.11 — тесты нажатий не работают с RNTL 14 в этой настройке (см. LAUNCH_PLAN)
Заблокировано: 3.1–3.3, 3.5–3.6 (аккаунты и ключи); 4.1, 4.3, 5.3, 5.10 (Docker, Android SDK, сервер)
Не создано: docs/OWNER_TODO.md, docs/PROPOSALS.md — по разделам 7.1 и 9 MASTER
