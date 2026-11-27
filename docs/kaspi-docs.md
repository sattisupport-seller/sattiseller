# Kaspi Shop API и XML-прайс — выжимка официальной документации

Собрал координатор 22.11.2026 по страницам guide.kaspi.kz (текст получен через загрузку страниц, не по памяти). Источник указан у каждого раздела. Чего в документации нет — так и помечено.

## 1. Общее (guide.kaspi.kz/partner/ru/shop/api/general/q3197)
- Заголовки: `Content-Type` (JSON), `X-Auth-Token` — токен, `Accept` — тип ответа (значение на странице не указано).
- Методы: GET — чтение, PUT — обновление или добавление, POST — загрузка.
- Параметры: `sort`, `page`, `filter`; набор зависит от запроса.
- На странице НЕТ: кодов ошибок, лимитов запросов, порядка получения токена.

## 2. Список заказов (…/api/orders/q3201)
- `GET https://kaspi.kz/shop/api/v2/orders`
- Заголовки: `Content-Type: application/vnd.api+json`, `X-Auth-Token: <token>`.
- `page[number]` — с 0; `page[size]` — максимум 100.
- `filter[orders][state]`: `NEW`, `SIGN_REQUIRED`, `PICKUP`, `DELIVERY`, `KASPI_DELIVERY`, `ARCHIVE`.
- `filter[orders][creationDate][$ge]` и `[$le]` — в миллисекундах. Максимальный диапазон на странице не указан.
- `filter[orders][status]`: `APPROVED_BY_BANK`, `ACCEPTED_BY_MERCHANT`, `COMPLETED`, `CANCELLED`, `CANCELLING`, `KASPI_DELIVERY_RETURN_REQUESTED`, `RETURNED`.
- `filter[orders][deliveryType]`: `PICKUP`, `DELIVERY` (страница упоминает и `KASPI_DELIVERY`); только если state не `PICKUP`.
- `filter[orders][signatureRequired]`: `true`/`false`; только если state не `SIGN_REQUIRED`.
- `include[orders]=user` — данные покупателя в разделе `included` (тип `customers`).
- Поиск по номеру: `filter[orders][code]=<код>` (…/orders/q3202).
- Ответ: `data[]` — `type: "orders"`, `id`, `attributes`, `relationships` (`entries`, `user`), `links`; `meta`: `pageCount`, `totalCount`.
- Атрибуты заказа: `code`, `totalPrice`, `customer` (`firstName`, `lastName`, `cellPhone`), `recipient`, `deliveryMode` (`DELIVERY_LOCAL`, `DELIVERY_PICKUP`, `DELIVERY_REGIONAL_TODOOR`, `DELIVERY_REGIONAL_PICKUP`), `isKaspiDelivery`, `paymentMode` (`PAY_WITH_CREDIT`, `PREPAID`), `signatureRequired`, `state`, `status`, `creationDate`, `approvedByBankDate`, `plannedDeliveryDate`, `reservationDate` (мс), `deliveryCost`, `deliveryCostForSeller`, `isImeiRequired`, `waybill`, `waybillNumber`, `deliveryAddress`, `category`, `courierTransmissionPlanningDate`, `courierTransmissionDate`, `express`, `returnedToWarehouse`, `preOrder`, `creditTerm`.
- Данные покупателя (`customer`, `deliveryAddress`) — персональные: хранить по нашим правилам, перед ИИ маскировать.

## 3. Состав заказа (…/api/orders/q3203)
- `GET https://kaspi.kz/shop/api/v2/orders/{orderId}/entries`
- Атрибуты позиции: `unitType` (`PIECES`, `MEASURABLE`, `MEASURABLE_PIECES`), `quantity`, `totalPrice`, `basePrice`, `deliveryCost`, `weight` (если указан), `entryNumber`, `category` (`code`, `title`), `isImeiRequired`.
- Связи: `product` → тип `masterproducts` (`/orderentries/{id}/product`), `deliveryPointOfService` → тип `pointofservices`.
- Артикул продавца (sku) в позиции на этой странице НЕ указан: товар определяется через связь `product` (`masterproducts`, у него есть связь `merchantProduct` — …/orders/q3207).

## 4. Смена статуса (для справки; приложение заказы не меняет)
- `POST https://kaspi.kz/shop/api/v2/orders`, тело `{"data": {"type": "orders", "id": "<id>", "attributes": {"code": "<code>", "status": "ACCEPTED_BY_MERCHANT"}}}` (…/orders/q3211).
- Выдача (`COMPLETED`) — с заголовками `X-Security-Code` (код покупателя) и `X-Send-Code` (…/orders/q3212).

## 5. Частичная отмена (…/orders/q3215)
- Страница при загрузке вернула ошибку сервера; по фрагменту из поиска: `PUT https://kaspi.kz/shop/api/orderPartialCancel/{orderId}`, тело — массив позиций `{"entry": {"id": "<orderentriesId>"}, "remainedQuantity": N, "remainedWeight": N, …}`.
- Вывод для нас: частичные отмены существуют → количество в позиции заказа может уменьшиться после первой синхронизации. Это влияет на прибыль и склад.

## 6. XML-прайс (…/shop/goods/price_list/q3251 и q2962)
- Корень: `<kaspi_catalog date="…" xmlns="kaspiShopping" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:schemaLocation="kaspiShopping http://kaspi.kz/kaspishopping.xsd">`; формат `date` не указан. Кодировка UTF-8.
- `<company>` — название, `<merchantid>` — ID продавца.
- `<offers><offer sku="…">`: sku — латинские буквы и цифры, до 20 символов, уникален в файле.
- `<model>` — название, `<brand>` — бренд.
- `<availabilities><availability available="yes|no" storeId="…" preOrder="…" stockCount="…"/>`: `storeId` — код склада из кабинета («Склады и магазины»); `preOrder` — дни предзаказа, максимум 30, не передавать, если предзаказ не нужен; `stockCount` — остаток.
- Цена: `<price>` — одна для всех городов; или `<cityprices><cityprice cityId="750000000">…</cityprice></cityprices>` (код города — через API). Цена с НДС, без пробелов, без дробной части, без лишних знаков.
- Автозагрузка: ссылка на http(s) в кабинете (Товары → Загрузить прайс-лист → Автоматическая загрузка). Kaspi забирает файл каждые 60 минут, если он изменился. Ошибки — Товары → История загрузок → вкладка «Обработано».
- Снятие с продажи через XML: официальная страница прямо не говорит. Есть `available="no"` (нет на складе). Сторонний интегратор (SelSup, не официально) пишет, что товар, которого нет в XML, Kaspi может снять с продажи.
