# Проверка функций от А до Я (К-30, 27.11.2026)

Каждая функция для продавца: где в коде, какие тесты её проверяют, статус.
Статусы: **✅ тесты** — проверено тестами; **🟡 моки** — проверено на моках, ждёт аккаунтов, Kaspi или сервера; **❌ нет теста** — не было (в этой проверке покрыто, см. «Добавлено»).
Тесты сервера — `server/tests/`, jest — `mobile/src/__qa__/`. Сквозные сценарии — раздел «Сквозные сценарии».

## 1. Подключение Kaspi и загрузка заказов
| Функция | Код | Тесты | Статус |
|---|---|---|---|
| Подключение токеном, проверка у Kaspi, шифрование токена | `app/kaspi.py` (connect, encrypt), `app/api.py` kaspi_connect; `app/settings/kaspi.tsx` | `test_kaspi.py`, `test_seller_access.py`; jest `kaspi-connect-flow`, `flows` | 🟡 моки (реальный Kaspi — KASPI_TEST.md) |
| Токен один раз, предупреждение «Понятно, подключить»; отключения нет | `api.py` kaspi_connect/kaspi_disconnect; `kaspi.tsx` | `test_seller_access.py` (`test_token_can_be_connected_only_once`, `test_kaspi_cannot_be_disconnected_separately`); jest `kaspi-connect-flow` | ✅ тесты |
| Без обучения подключение закрыто | `api.py` (onboarding_required); `kaspi.tsx` | `test_onboarding.py`; jest `kaspi-onboarding-gate` | ✅ тесты |
| Первая загрузка: 7 дней сразу, догрузка 90 дней, прогресс | `kaspi.py` sync/_backfill_pass | `test_kaspi_first_load.py`, `test_e2e_seller_journey.py` (а) | 🟡 моки |
| Синхронизация раз в 15 минут без дублей; ночное перечитывание (03:00 по Алматы) заказов с открытым окном возврата (не выданы или выданы ≤ 17 дней), свежие первыми | `kaspi.py` sync_due, refresh_open_orders; `scheduler.py` nightly_due | `test_kaspi.py`, `test_independent_check_fixes.py` (D1, D2) | 🟡 моки |
| Коды складов (storeId) | `kaspi.py` set_store_ids; `kaspi.tsx` | `test_kaspi.py`; jest `kaspi-store-flow` | 🟡 моки |
| Названия и категории товаров из Kaspi | `kaspi.py` _product_for | `test_kaspi.py` | 🟡 моки |

## 2. Прибыль
| Функция | Код | Тесты | Статус |
|---|---|---|---|
| Формула продажи и возврата (округление до тиына по строке, показ — в тенге) | `app/finance.py` | `test_units.py`, `test_golden.py`, `test_finance_properties.py`, **`test_e2e_profit_by_hand.py`** | ✅ тесты |
| Себестоимость с датой (ко всей истории / с даты) | `api.py` cost_version_create; `reports.py` unit_cost_on; `product/cost/[id].tsx` | `test_qa_full.py`, `test_api.py`; jest `product-cost-flow` | ✅ тесты |
| Комиссии по категориям с датой | `api.py` commissions; `reports.py` rate_on; `settings/commissions.tsx` | `test_flow.py`, `test_tax_api.py`; jest `commissions-settings` | ✅ тесты |
| Рассрочка и кредит — тариф 10,9 % (меняется продавцом, по дате заказа; записанная ставка задним числом не меняется) | `kaspi.py` installment_rate_bp | `test_kaspi.py`, `test_e2e_profit_by_hand.py`, `test_independent_check_fixes.py` (D5) | ✅ тесты |
| Kaspi Доставка за счёт продавца — расход; нет поля — 0 | `kaspi.py` _reconcile | `test_kaspi.py`, `test_e2e_profit_by_hand.py` | ✅ тесты (реальное поле — KASPI_TEST.md) |
| Реклама и прочие расходы (прибыль магазина) | `api.py` expenses; `settings/expenses.tsx` | `test_flow.py`, `test_qa_security.py`; jest `expenses-settings` | ✅ тесты |
| Налог (ставка с датой, возврат налога при возврате) | `api.py` tax; `reports.py` tax_rate_bp_on; `settings/tax.tsx` | `test_tax.py`, `test_tax_api.py`, `test_e2e_profit_by_hand.py`; jest `tax-settings` | ✅ тесты |

### Ручная сверка прибыли (тест `test_e2e_profit_by_hand.py`)
Пересчитано в К-33 А2 (тарифы Kaspi 2026; продавец не плательщик НДС): комиссия категории 12,5 % с НДС, рассрочка 0-0-24 — 13,0 % с НДС, доставка Kaspi 500 ₸ без НДС → 580 ₸ с НДС 16 %, налог 3 %, себестоимость K0 = 2 000 ₸, K1 = 3 000 ₸.

| Заказ | Продажа | Себестоимость | Комиссия | Доставка | Налог | Прибыль |
|---|---|---|---|---|---|---|
| A: 2 × K0 по 5 000, доставка продавца 500 без НДС | 10 000 | 4 000 | 1 250 (12,5 %) | 580 | 300 | **3 870** |
| B: 1 × K1 8 000, рассрочка 0-0-24 | 8 000 | 3 000 | 1 040 (13,0 %) | 0 | 240 | **3 720** |
| C: 1 × K0 5 000, возврат на склад | 5 000 | 2 000 | 625 | 0 | 150 | продажа 2 225; возврат −5 000 + 2 000 + 625 + 150 = −2 225 → **0** |
| **Итого** | чистые продажи 23 000 − 5 000 = **18 000** | | | | | **7 590 ₸** |

Расчёт приложения совпал до тенге (`kpi.profit_minor = 759 000` тиынов, покрытие 100 %). В К-30 было 7 888 ₸ — по ставкам 12 % и 10,9 % (10,9 % — основная ставка без НДС, а не рассрочка) и доставке без НДС.

К-30: **Сверка нашла ошибку:** заказы B и C считались «прибыль неизвестна» — у заказа без `deliveryCostForSeller` доставка была «неизвестно», у возврата Kaspi — неизвестная комиссия к возврату. Исправлено (`kaspi._reconcile`, `reports.build_facts`).

## 3. Отмены и возвраты
| Функция | Код | Тесты | Статус |
|---|---|---|---|
| Отмена и частичная отмена Kaspi (движение склада «cancel»); пустой ответ позиций не удаляет заказ | `kaspi.py` _reconcile, _log_cancel | `test_kaspi.py` (partial_cancel), `test_stock_kaspi.py`, `test_independent_check_fixes.py` (D8) | 🟡 моки |
| Возврат Kaspi — по каждой позиции (RETURNED); старый возврат при первой загрузке датируется выдачей, новый — временем синхронизации (Kaspi не даёт дату возврата) | `kaspi.py` _ensure_full_return | `test_kaspi_returns.py`, `test_independent_check_fixes.py` (D4) | 🟡 моки |
| Окно возврата 14 дней от выдачи + 3 дня | `kaspi.py` return_window_open | `test_kaspi.py` | 🟡 моки |
| Подтверждение возврата на склад | `api.py` stock_confirm_returns; `stock.tsx` | `test_kaspi_returns.py`; jest `stock-return-confirm`, `seller-journey` | ✅ тесты |

## 4. Отчёты и выгрузки
| Функция | Код | Тесты | Статус |
|---|---|---|---|
| Обзор, заказы, товары, разбивка прибыли, кэш отчётов | `reports.py`, `reportcache.py`; вкладки | `test_flow.py`, `test_report_cache.py`, `test_report_snapshot.py`; jest `screens`, `screens-smoke` | ✅ тесты |
| Excel по прибыли | `exports.py` profit_workbook | `test_exports.py`, `test_e2e_seller_journey.py` (а) | ✅ тесты |
| «Скачать мои данные» (ZIP), закрыто при деактивации | `exports.py` user_export_zip | `test_exports.py`, `test_deactivation.py` | ✅ тесты |
| Импорт затрат из Excel | `imports.py`; `import.tsx` | `test_flow.py`, `test_import_limits.py`; jest `import-flow`, `import-screen` | ✅ тесты |

## 5. Склад
| Функция | Код | Тесты | Статус |
|---|---|---|---|
| Остаток обязателен вместе с себестоимостью; подсказка из прайса | `api.py` _unconfigured, cost-versions; `quick-cost.tsx`, `product/cost/[id].tsx` | `test_stock_with_cost.py`; jest `quick-cost-flow`, `product-cost-flow`, `seller-journey` | ✅ тесты |
| Журнал: инвентаризация, приход, продажи после ввода, возвраты | `stock.py` stock_states | `test_stock.py`, `test_stock_flow.py`, `test_stock_scenarios.py`; jest `stock-first-receipt` | ✅ тесты |
| Уведомления 10/5/3/0, один раз на порог | `api.py` stock_alerts; `stock.py` | `test_stock_flow.py`, `test_e2e_seller_journey.py` (а) | ✅ тесты (пуш — моки) |
| Снятие с продажи через прайс (`available="no"`) | `api.py` delist/relist; `kaspi.py` price_list_xml | `test_stock_flow.py`, `test_kaspi.py` | ✅ тесты |

## 6. Прайс-лист Kaspi
| Функция | Код | Тесты | Статус |
|---|---|---|---|
| Импорт прайса продавца (XML, защита от DTD) | `kaspi.py` import_catalog | `test_kaspi.py`; jest `kaspi-catalog-flow` | ✅ тесты |
| Наш файл по секретной ссылке; ссылка только после импорта | `kaspi.py` price_list_xml; `api.py` kaspi_price_list | `test_kaspi.py`, `test_security_low_fixes.py` | 🟡 моки («История загрузок» — на реальном кабинете) |
| При деактивации — 503 без файла (не «пусто») | `api.py` kaspi_price_list | `test_deactivation.py` | ✅ тесты |

## 7. ИИ
| Функция | Код | Тесты | Статус |
|---|---|---|---|
| Помощник: ответы по данным, отказы, маскировка покупателей | `ai.py`, `privacy.py` | `test_ai_*.py`, `test_buyer_masking.py`, `test_privacy.py` | ✅ тесты (живая модель — по ключу) |
| 30 запросов в день на аккаунт (все устройства), сутки — по Алматы; вопросы и черновики вместе | `ai.py` check_quota | `test_ai_quota_per_account.py` (лимит 30, два устройства), `test_ai_quota_race.py`, `test_independent_check_fixes.py` (D9), `test_e2e_seller_journey.py` (б) | ✅ тесты |
| Бюджет ИИ, письма 80/100 % | `ai.py` require_budget, check_budget_alerts | `test_ai_budget.py`, `test_ai_budget_thresholds.py` | ✅ тесты |
| Карточка товара (фото, проверка чисел, шаблон при сбое, резерв квоты) | `draft_ai.py`, `api.py` ai_product_draft | `test_draft_ai.py`, `test_ai_drafts_k12.py`, `test_security_audit_fixes.py`; jest `product-draft-flow`, `draft-consent-flow` | ✅ тесты |
| Ответ покупателю (шаблон) | `ai.py` reply_draft | `test_flow.py`; jest `reply-draft-flow` | ✅ тесты |
| Жалоба на ответ и на текст ИИ | `api.py` ai_feedback | `test_admin_ai_feedback.py`; jest `assistant-complaint`, `reply-draft-flow` | ✅ тесты |

## 8. Уведомления
| Функция | Код | Тесты | Статус |
|---|---|---|---|
| Токен устройства, очередь, тихие часы 22:00–09:00, сводка по понедельникам | `push.py`; `lib/push.ts`, `settings/notifications.tsx` | `test_push.py`; jest `notifications-flow` | 🟡 моки (реальная отправка — Firebase/APNs) |
| Письма: коды, удаление, деактивация, хранение 0/60/83/90, оповещения владельцу | `mailer.py`, `billing.py`, `owner_alerts.py` | `test_mail.py`, `test_account_deletion.py`, `test_owner_alerts.py`, `test_qa_money_scheduler.py` | 🟡 моки (SMTP — после почтового сервиса) |

## 9. Вход, согласие, обучение, демо
| Функция | Код | Тесты | Статус |
|---|---|---|---|
| Вход Apple и Google (проверка токена, отзыв токена Apple) | `social_auth.py`, `apple_tokens.py`; `login.tsx` | `test_social_auth.py`, `test_apple_revoke.py`; jest `login-flow` | 🟡 моки (аккаунты Apple/Google) |
| Согласие при регистрации (галочка с ИИ), обновлённое один раз | `api.py` _record_terms; `login.tsx`, `terms-consent.tsx` | `test_terms_consent.py`, `test_ai_consent_version.py`; jest `login-flow` | ✅ тесты |
| Обучение: 14 шагов, 5 минут, отметка у аккаунта | `onboarding/*`; `api.py` onboarding_complete | `test_onboarding.py`; jest `onboarding-flow` | ✅ тесты |
| Демо: шаблон, 24 часа, 3 в сутки с устройства | `demo.py`, `demo_template.py` | `test_demo_*.py`; jest `welcome-flow` | ✅ тесты |

## 10. Подписка, номер продавца, устройства
| Функция | Код | Тесты | Статус |
|---|---|---|---|
| Покупки App Store и Google Play, уведомления, восстановление | `store_billing.py`; `paywall.tsx`, `lib/purchases.ts` | `test_store_billing.py`; jest `paywall-store`, `paywall-flow` | 🟡 моки (аккаунты, dev build) |
| Пробный период: только после Kaspi; один на телефон, магазин, аккаунт | `billing.py` trial_decision; `device_trust.py` | `test_store_billing.py`, `test_billing.py`, `test_billing_marks.py`, `test_e2e_seller_journey.py` (в) | 🟡 моки (DeviceCheck/Play Integrity) |
| Номер продавца, один магазин — один аккаунт, второй магазин запрещён | `seller_access.py`; `api.py` shops_create | `test_seller_access.py` | ✅ тесты |
| Несколько устройств — те же данные (расход с одного телефона виден на другом) | `auth.py` shop_for | `test_e2e_seller_journey.py` (б) | ✅ тесты |
| Конец подписки: экран, хранение 90 дней; доступ от владельца перезапускает отсчёт | `billing.py`; `subscription-ended.tsx` | `test_billing.py`, `test_qa_money_scheduler.py`, `test_independent_check_fixes.py` (D3); jest `subscription-ended-flow` | ✅ тесты |

## 11. Удаление и деактивация
| Функция | Код | Тесты | Статус |
|---|---|---|---|
| Удаление сразу (приложение и веб), все данные, письмо | `accounts.py`; `delete-account.tsx`, `web.py` | `test_account_deletion.py`, `test_web.py`, `test_security_audit_fixes.py`; jest `delete-account-flow` | ✅ тесты |
| Деактивация 30 дней, восстановление только с оплатой, автоудаление | `accounts.py`; `account-deactivated.tsx` | `test_deactivation.py`; jest `account-deactivated-flow` | ✅ тесты |

## 12. Админка владельца
| Функция | Код | Тесты | Статус |
|---|---|---|---|
| Вход по почте только для владельца + 2FA, перебор кода ограничен | `api.py` _email_login_allowed; `admin.py` | `test_admin_email_login.py`, `test_admin.py`, `test_security_audit_fixes.py`, `test_e2e_seller_journey.py` (г) | ✅ тесты |
| Доступ без подписки 1/3/6 мес., блокировка, окно токена 24 ч, «Особые условия», журнал | `seller_access.py`, `admin.py` | `test_seller_access.py`, `test_e2e_seller_journey.py` (г) | ✅ тесты |

## Сквозные сценарии (К-30 п.2)
| Сценарий | Сервер (API) | jest |
|---|---|---|
| а) новый продавец от входа до удаления | `test_e2e_seller_journey.py::test_a_new_seller_full_journey` | `seller-journey.test.tsx` (обучение → Kaspi → себестоимость и остаток → возврат) |
| б) второе устройство: те же данные, общий лимит | `::test_b_second_device_same_data_and_shared_quota` | — (экраны те же; данные — сервер) |
| в) повторный пробный период — нельзя | `::test_c_no_second_trial_for_same_phone_or_same_kaspi_shop` | jest `paywall-store` |
| г) владелец в админке | `::test_d_owner_admin_email_2fa_special_access_block_reconnect` | — (веб-админка, не приложение) |
| Ручная сверка прибыли | `test_e2e_profit_by_hand.py` | — |

## Добавлено в этой проверке
- Сквозные сценарии а–г и ручная сверка прибыли (раньше не было).
- Ночной цикл перечитывания Kaspi тестами не был покрыт и **не работал** (D1) — теперь покрыт.

## Независимая перепроверка (К-30 п.3, отдельный агент, не писал этот код)
Ручная сверка прибыли **подтверждена** его собственным расчётом (7 888 ₸, 18 000 ₸, покрытие 100 %). Найдено и исправлено с тестами (`test_independent_check_fixes.py`):

| ID | Уровень | Что было | Исправление |
|---|---|---|---|
| D1 | CRITICAL | ночной поток перечитывания Kaspi падал на импорте несуществующей константы — в бою не запускался ни разу; поздние возвраты и выдачи не попадали в Satti | константа `NIGHTLY_HOUR`, решение «пора ли» — отдельной функцией с тестом |
| D2 | HIGH | перечитывались 2000 **самых старых** заказов — у крупного магазина свежие не проверялись | в выборке только заказы с открытым окном возврата, свежие первыми |
| D3 | HIGH | после доступа от владельца отсчёт 90 дней шёл от старого окончания подписки — данные могли удалиться сразу | выдача и отмена доступа сбрасывают отсчёт; 90 дней — от окончания доступа |
| D4 | MEDIUM | все старые возвраты при первой загрузке ложились на день подключения | старый возврат датируется выдачей заказа |
| D5 | MEDIUM | тариф рассрочки с будущей даты применялся сразу и переписывал старые заказы | ставка — на дату заказа; записанная не меняется |
| D7 | MEDIUM | товар с одним возвратом в периоде показывался «нет данных», бейдж «в минусе» пропадал | прибыль известна и отрицательна |
| D8 | LOW–MEDIUM | пустой ответ позиций Kaspi удалял позиции заказа вместе с возвратами | пустой ответ у неотменённого заказа игнорируется |
| D9 | LOW | сутки лимита ИИ — по UTC (сброс в 05:00 по Алматы) | сутки по Алматы |

Не исправлено (решение владельца или ТЗ):
- **D6** — налог при возврате берётся по ставке на дату возврата, как прямо требует ТЗ 2.1, раздел 7.1. Если ставка налога меняется между продажей и возвратом, итог заказа не равен нулю (пример: продажа без налога, возврат после введения 3 % → +150 ₸ на 5 000 ₸). Вопрос владельцу: оставить по ТЗ или возвращать налог по ставке продажи (рекомендация — по ставке продажи).
- **D10** (LOW, только показ «продано всего» при частичной отмене старого заказа) и **D11** (магазин, ни разу не оформивший подписку, не попадает под удаление через 90 дней — правило хранения 0/60/83/90 не меняем по К-21) — записаны в LAUNCH_PLAN.

## Что нельзя проверить без аккаунтов и сервера — когда и как
| Что | Когда | Как |
|---|---|---|
| Сборка EAS (dev build и магазинная) | после аккаунтов Apple/Google | `eas build --profile development` → установить на телефоны; `--profile production` |
| Docker-образ, Caddy, `deploy.sh setup/up`, cron копий | после покупки сервера | LAUNCH.md шаги 3–5, репетиция переезда (DR.md) |
| Покупки и пробный период (песочницы) | после аккаунтов и dev build | песочница App Store (TestFlight), лицензионные тестеры Google Play |
| DeviceCheck / Play Integrity | после ключей | второй аккаунт на том же телефоне — без пробного периода |
| Пуши | после Firebase и APNs в EAS | `SATTI_PUSH_MODE=expo`, уведомление склада и сводка на телефон |
| Вход Apple и Google | после аккаунтов | вход на iPhone и Android, отзыв токена при удалении |
| Реальный Kaspi | после тестового магазина | `docs/KASPI_TEST.md` (в т.ч. поле `deliveryCostForSeller`, комиссия по возврату, ответ 503 прайса) |
| Почта (SPF/DKIM/DMARC) | после почтового сервиса | коды во «Входящих» Gmail, Mail.ru, iCloud |
| Телефон: все экраны, обучение, тёмная тема | после dev build | `docs/DEVICE_CHECKLIST.md` |
