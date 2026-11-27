"""Модели ответов API (ТЗ 2.1, задача 1). Из них OpenAPI строит типы для приложения.

Деньги — целые тиыны (поля *_minor), ставки и доли — базисные пункты (поля *_bp), даты — ISO-строки.
Модели описывают то, что реально отдают функции reports.py / billing.py / api.py.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class PeriodOut(BaseModel):
    from_: str = Field(alias="from")
    to: str

    model_config = {"populate_by_name": True}


# ---------- обзор ----------

class KpiOut(BaseModel):
    net_sales_minor: int
    net_sales_delta_bp: int | None
    profit_minor: int
    profit_delta_bp: int | None
    coverage_bp: int
    orders_count: int
    orders_delta: int
    returns_cancels_count: int
    returns_cancels_delta: int


class InMinusItem(BaseModel):
    product_id: str
    sku: str
    name: str
    profit_minor: int | None


class ManyReturnsItem(BaseModel):
    product_id: str
    sku: str
    name: str
    returned_qty: int


class AttentionOut(BaseModel):
    in_minus: list[InMinusItem]
    no_cost_count: int
    many_returns: list[ManyReturnsItem]
    not_configured_count: int = 0  # К-24: товаров без себестоимости или без остатка — «введите себестоимость и остаток»


class BestProductOut(BaseModel):
    product_id: str
    sku: str
    name: str
    profit_minor: int | None
    margin_bp: int | None


class SeriesOut(BaseModel):
    days: list[str]
    profit: list[int]
    sales: list[int]
    prev_profit: list[int]
    prev_sales: list[int]


class OverviewOut(BaseModel):
    shop_id: str
    period: PeriodOut
    comparison_period: PeriodOut
    history_note: str | None = None  # К-17.3: период раньше первой загрузки Kaspi
    data_from: str | None = None  # К-18.4: дата, с которой есть данные Kaspi (за 90 дней)
    data_as_of: str
    is_today_in_period: bool
    kpi: KpiOut
    attention: AttentionOut
    best_products: list[BestProductOut]
    series: SeriesOut


# ---------- прибыль ----------

class BreakdownStepOut(BaseModel):
    key: str
    minor: int
    label: str
    rate_bp: int | None = None


class MissingOut(BaseModel):
    product_id: str
    sku: str
    name: str
    reason: str


class ProfitBreakdownOut(BaseModel):
    period: PeriodOut
    steps: list[BreakdownStepOut]
    coverage_bp: int
    net_sales_all_minor: int
    missing: list[MissingOut]
    note: str


# ---------- заказы ----------

class ReturnOut(BaseModel):
    day: str
    qty: int
    refund_minor: int
    profit_delta_minor: int | None


class OrderItemOut(BaseModel):
    product_id: str
    sku: str
    name: str
    qty: int
    unit_price_minor: int
    gross_minor: int
    commission_minor: int | None
    commission_source: str
    tax_minor: int | None = None
    tax_rate_bp: int | None = None
    landed_minor: int | None
    cost_source: str
    profit_minor: int | None
    returns: list[ReturnOut]


class OrderDetailOut(BaseModel):
    id: str
    number: str
    status: str
    created_at: str
    completed_at: str | None
    items: list[OrderItemOut]


# ---------- товары ----------

class ProductRowOut(BaseModel):
    product_id: str
    sku: str
    name: str
    category: str
    sold_qty: int
    returned_qty: int
    net_sales_minor: int
    profit_minor: int | None
    margin_bp: int | None
    badges: list[str]


class EconomicsOut(BaseModel):
    avg_price_minor: int
    landed_minor: int
    commission_bp: int
    commission_minor: int
    delivery_minor: int
    tax_minor: int | None = None
    profit_per_unit_minor: int


class CurrentCostOut(BaseModel):
    purchase_minor: int
    delivery_to_warehouse_minor: int
    packaging_minor: int
    other_minor: int
    effective_from: str | None
    source: str


class CostHistoryOut(BaseModel):
    id: str
    effective_from: str | None
    landed_unit_minor: int
    source: str


class ProductReturnOut(BaseModel):
    day: str
    qty: int
    refund_minor: int
    known: bool


class DailyUnitsOut(BaseModel):
    day: str
    qty: int


class ProductDetailOut(BaseModel):
    product: ProductRowOut
    period: PeriodOut
    daily_units: list[DailyUnitsOut]
    economics: EconomicsOut | None
    current_cost: CurrentCostOut | None
    cost_history: list[CostHistoryOut]
    returns: list[ProductReturnOut]
    data_complete: bool
    commission_note: str | None = None  # К-16.2: нет ставки комиссии для категории


class MissingCostProductOut(BaseModel):
    product_id: str
    sku: str
    name: str
    category: str
    # К-24: товар настроен, когда указаны и себестоимость, и остаток
    needs_cost: bool = True
    needs_stock: bool = True
    stock_hint: int | None = None  # stockCount из прайса продавца — подставить, продавец подтверждает


# ---------- комиссии, налог, расходы ----------

class CommissionOut(BaseModel):
    id: str
    category: str
    rate_bp: int
    effective_from: str | None
    source: str
    verified: bool
    demo: bool


class CommissionsOut(BaseModel):
    items: list[CommissionOut]


class CommissionCreatedOut(BaseModel):
    id: str
    rate_bp: int


class TaxRowOut(BaseModel):
    id: str
    enabled: bool
    rate_bp: int | None
    effective_from: str | None
    created_at: str


class TaxOut(BaseModel):
    current: TaxRowOut | None
    items: list[TaxRowOut]


# ---------- подписка, магазины, профиль ----------

class SubscriptionOut(BaseModel):
    state: str
    access_until: str | None
    store: str
    price_text: str
    trial_days: int
    data_delete_on: str | None
    trial_available: bool | None = None


class ShopOut(BaseModel):
    id: str
    name: str
    timezone: str
    language: str
    is_demo: bool


class ShopsOut(BaseModel):
    items: list[ShopOut]


class MeOut(BaseModel):
    demo: bool
    id: str | None = None
    email: str | None = None
    name: str | None = None
    locale: str = "ru"
    age_confirmed: bool | None = None
    terms_consent_required: bool = False  # 1.19: нужно принять обновлённые условия
    seller_number: str | None = None  # К-21: номер продавца (8 цифр) — назвать в поддержке
    deactivated: bool = False  # К-21: аккаунт деактивирован — в приложении только экран восстановления
    delete_on: str | None = None  # дата автоудаления при деактивации (ISO)


class AgeConfirmOut(BaseModel):
    age_confirmed: bool


# ---------- списки ----------

class OrderSummaryOut(BaseModel):
    id: str
    number: str
    status: str
    created_at: str
    items_count: int
    summary: str
    total_minor: int


class OrdersPageOut(BaseModel):
    items: list[OrderSummaryOut]
    total: int
    next_cursor: str | None


class CoverageOut(BaseModel):
    complete: int
    total: int


class ProductsPageOut(BaseModel):
    items: list[ProductRowOut]
    total: int
    no_cost_count: int = 0  # К-18: товаров без себестоимости — для подсказки
    coverage: CoverageOut
    next_cursor: str | None


class MissingCostsOut(BaseModel):
    items: list[MissingCostProductOut]


class ExpenseOut(BaseModel):
    id: str
    kind: str
    amount_minor: int
    period_start: str
    period_end: str


class ExpensesOut(BaseModel):
    items: list[ExpenseOut]


class CostVersionOut(BaseModel):
    id: str
    purchase_minor: int
    delivery_to_warehouse_minor: int
    packaging_minor: int
    other_minor: int
    landed_unit_minor: int
    effective_from: str | None
    source: str
    cancelled: bool


class CostVersionsOut(BaseModel):
    items: list[CostVersionOut]


class AIQuotaOut(BaseModel):
    limit: int
    remaining: int
    consent_active: bool
    consent_version: str | None
