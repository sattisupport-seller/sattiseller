// Типы ответов API /v1. Написаны вручную по серверным моделям (server/app/reports.py, api.py).
// Суммы — целые тиыны (поля *_minor). Ставки и доли — базисные пункты (поля *_bp).

export type Period = '7d' | '30d' | '90d' | 'today' | string;

export type ShopSummary = { id: string; name: string; timezone: string; language: 'ru' | 'kk'; is_demo: boolean };

export type Overview = {
  shop_id: string;
  period: { from: string; to: string };
  comparison_period: { from: string; to: string };
  data_as_of: string;
  is_today_in_period: boolean;
  kpi: {
    net_sales_minor: number;
    net_sales_delta_bp: number | null;
    profit_minor: number;
    profit_delta_bp: number | null;
    coverage_bp: number;
    orders_count: number;
    orders_delta: number;
    returns_cancels_count: number;
    returns_cancels_delta: number;
  };
  attention: {
    in_minus: { product_id: string; sku: string; name: string; profit_minor: number | null }[];
    no_cost_count: number;
    many_returns: { product_id: string; sku: string; name: string; returned_qty: number }[];
  };
  best_products: { product_id: string; sku: string; name: string; profit_minor: number | null; margin_bp: number | null }[];
  series: { days: string[]; profit: number[]; sales: number[]; prev_profit: number[]; prev_sales: number[] };
};

export type BreakdownStep = { key: string; minor: number; label: string; rate_bp?: number | null };

// Налог (ТЗ 2.1, раздел 7): ставка в базисных пунктах; enabled = false — налог выключен с этой даты.
export type TaxRow = { id: string; enabled: boolean; rate_bp: number | null; effective_from: string | null; created_at: string };
export type TaxSettings = { current: TaxRow | null; items: TaxRow[] };

export type ProfitBreakdown = {
  period: { from: string; to: string };
  steps: BreakdownStep[];
  coverage_bp: number;
  net_sales_all_minor: number;
  missing: { product_id: string; sku: string; name: string; reason: 'no_cost' | 'incomplete' }[];
  note: string;
};

export type OrderStatus = 'completed' | 'returned' | 'partial_return' | 'cancelled' | 'in_progress' | 'pending';

export type OrderRow = {
  id: string;
  number: string;
  status: OrderStatus;
  created_at: string;
  items_count: number;
  summary: string;
  total_minor: number;
};

export type OrdersPage = { items: OrderRow[]; total: number; next_cursor: string | null };

export type OrderDetail = {
  id: string;
  number: string;
  status: OrderStatus;
  created_at: string;
  completed_at: string | null;
  items: {
    product_id: string;
    sku: string;
    name: string;
    qty: number;
    unit_price_minor: number;
    gross_minor: number;
    commission_minor: number | null;
    commission_source: string;
    tax_minor?: number | null;
    tax_rate_bp?: number | null;
    landed_minor: number | null;
    cost_source: string;
    profit_minor: number | null;
    returns: { day: string; qty: number; refund_minor: number; profit_delta_minor: number | null }[];
  }[];
};

export type ProductBadge = 'in_minus' | 'no_cost' | 'many_returns' | 'no_sales';

export type ProductRow = {
  product_id: string;
  sku: string;
  name: string;
  category: string;
  sold_qty: number;
  returned_qty: number;
  net_sales_minor: number;
  profit_minor: number | null;
  margin_bp: number | null;
  badges: ProductBadge[];
};

export type ProductsPage = {
  items: ProductRow[];
  total: number;
  coverage: { complete: number; total: number };
  next_cursor: string | null;
};

export type ProductDetail = {
  product: ProductRow;
  period: { from: string; to: string };
  daily_units: { day: string; qty: number }[];
  economics: {
    avg_price_minor: number;
    landed_minor: number;
    commission_bp: number;
    commission_minor: number;
    delivery_minor: number;
    tax_minor?: number | null;
    profit_per_unit_minor: number;
  } | null;
  current_cost: {
    purchase_minor: number;
    delivery_to_warehouse_minor: number;
    packaging_minor: number;
    other_minor: number;
    effective_from: string | null;
    source: string;
  } | null;
  cost_history: { id: string; effective_from: string | null; landed_unit_minor: number; source: string }[];
  returns: { day: string; qty: number; refund_minor: number; known: boolean }[];
  data_complete: boolean;
};

export type CostVersion = {
  id: string;
  purchase_minor: number;
  delivery_to_warehouse_minor: number;
  packaging_minor: number;
  other_minor: number;
  landed_unit_minor: number;
  effective_from: string | null;
  source: string;
  cancelled: boolean;
};

export type ImportPreview = {
  total_rows: number;
  valid_rows: number;
  counts: { new: number; updated: number; unchanged: number };
  errors_count: number;
  errors: { row: number; sku: string | null; field: string; message: string }[];
  new_products_without_cost: number;
  status: string;
};

export type ImportUpload = {
  id: string;
  filename: string;
  columns: string[];
  rows_total: number;
  mapping: Record<string, string | null>;
  missing_required: string[];
  fields: string[];
};

export type AskAnswer = {
  turnId: string;
  conversationId: string;
  answerTemplate: string;
  renderedAnswer: string;
  period: { from: string; to: string } | null;
  comparisonPeriod: { from: string; to: string } | null;
  dataAsOf: string;
  evidence: { factId: string; label: string; kind: string; value: string | number; text?: string; snapshotId: string }[];
  missingData: string[];
  suggestedActions: { type: string; entityId?: string; label: string }[];
  confidence: 'high' | 'medium' | 'low' | null;
  confidenceReason: string | null;
  lang: 'ru' | 'kk';
};

export type AIQuota = { limit: number; remaining: number; consent_active: boolean; consent_version: string | null };

export type Conversation = { id: string; title: string; created_at: string };

export type ProductDraft = {
  titles: string[];
  description: string;
  characteristics: { name: string; value: string }[];
  warnings: string[];
  languages: string;
  photosUsed: number;
};

export type ReplyDraft = { reply: string; warnings: string[] };

export type Commission = { id: string; category: string; rate_bp: number; effective_from: string | null; source: string; verified: boolean; demo: boolean };

export type Expense = { id: string; kind: 'ads' | 'other'; amount_minor: number; period_start: string; period_end: string };

export type AppConfig = {
  min_supported_version_ios: string;
  min_supported_version_android: string;
  maintenance_message: string | null;
  ai_service_name: string;
  privacy_url: string;
  terms_url: string;
  flags: { kaspi_connection: boolean; ai_assistant: boolean; subscription: boolean };
};

export type ApiErrorBody = { error: { code: string; message: string; error_id: string } };
