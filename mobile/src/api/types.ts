// Типы ответов API /v1.
// Часть типов берётся из схемы сервера (schema.ts, генерируется командой `npm run gen:api`).
// Остальные пока написаны вручную по серверным моделям: их список — в docs/progress-2.1.md (задача 1).
// Суммы — целые тиыны (поля *_minor). Ставки и доли — базисные пункты (поля *_bp).
import type { components } from './schema';

type S<K extends keyof components['schemas']> = components['schemas'][K];

export type Period = '7d' | '30d' | '90d' | 'today' | string;

export type ShopSummary = { id: string; name: string; timezone: string; language: 'ru' | 'kk'; is_demo: boolean };

// Обзор, прибыль, налог, комиссии — из схемы сервера
export type Overview = S<'OverviewOut'>;

export type BreakdownStep = S<'BreakdownStepOut'>;

export type TaxRow = S<'TaxRowOut'>;
export type TaxSettings = S<'TaxOut'>;

export type ProfitBreakdown = Omit<S<'ProfitBreakdownOut'>, 'missing'> & {
  missing: { product_id: string; sku: string; name: string; reason: 'no_cost' | 'incomplete' }[];
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

export type OrderDetail = Omit<S<'OrderDetailOut'>, 'status'> & { status: OrderStatus };

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

export type ProductDetail = Omit<S<'ProductDetailOut'>, 'product'> & { product: ProductRow };

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

export type Commission = S<'CommissionOut'>;

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
