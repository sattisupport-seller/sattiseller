// Запросы данных через React Query: кэш, повторы и обновление при возврате в приложение.
import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import type { components } from './schema';
import { request } from './client';
import type {
  AIQuota,
  AppConfig,
  AskAnswer,
  Commission,
  Conversation,
  CostVersion,
  Expense,
  ImportPreview,
  ImportUpload,
  OrderDetail,
  OrdersPage,
  Overview,
  ProductDetail,
  ProductDraft,
  ProductsPage,
  ProfitBreakdown,
  ReplyDraft,
  ShopSummary,
  TaxRow,
  TaxSettings,
} from './types';

const STALE = 60_000;

export function useAppConfig() {
  return useQuery({ queryKey: ['app-config'], queryFn: () => request<AppConfig>('/app/config', { auth: false }), staleTime: 10 * 60_000 });
}

// Помощник показывается только при включённом на сервере флаге (по умолчанию выключен на запуске).
// Пока конфиг не загружен — помощник скрыт: без заглушек «скоро появится».
export function useAssistantEnabled(): boolean {
  return useAppConfig().data?.flags.ai_assistant === true;
}

export function useShops(enabled = true) {
  return useQuery({
    queryKey: ['shops'],
    queryFn: () => request<{ items: ShopSummary[] }>('/shops'),
    enabled,
  });
}

export function useOverview(shopId: string | null, period: string) {
  return useQuery({
    queryKey: ['overview', shopId, period],
    queryFn: () => request<Overview>(`/shops/${shopId}/overview?period=${period}`),
    enabled: !!shopId,
    staleTime: STALE,
  });
}

export function useProfitBreakdown(shopId: string | null, period: string) {
  return useQuery({
    queryKey: ['breakdown', shopId, period],
    queryFn: () => request<ProfitBreakdown>(`/shops/${shopId}/profit-breakdown?period=${period}`),
    enabled: !!shopId,
    staleTime: STALE,
  });
}

export function useOrders(shopId: string | null, period: string, status: string | null, q: string) {
  return useInfiniteQuery({
    queryKey: ['orders', shopId, period, status, q],
    initialPageParam: null as string | null,
    queryFn: ({ pageParam }) => {
      const params = new URLSearchParams({ period, limit: '50' });
      if (status) params.set('status', status);
      if (q) params.set('q', q);
      if (pageParam) params.set('cursor', pageParam);
      return request<OrdersPage>(`/shops/${shopId}/orders?${params.toString()}`);
    },
    getNextPageParam: (last) => last.next_cursor,
    enabled: !!shopId,
    staleTime: STALE,
  });
}

export function useOrder(shopId: string | null, orderId: string) {
  return useQuery({
    queryKey: ['order', shopId, orderId],
    queryFn: () => request<OrderDetail>(`/shops/${shopId}/orders/${orderId}`),
    enabled: !!shopId,
  });
}

export function useProducts(shopId: string | null, period: string, filter: string | null, sort: string, q: string) {
  return useInfiniteQuery({
    queryKey: ['products', shopId, period, filter, sort, q],
    initialPageParam: null as string | null,
    queryFn: ({ pageParam }) => {
      const params = new URLSearchParams({ period, sort, limit: '50' });
      if (filter) params.set('filter', filter);
      if (q) params.set('q', q);
      if (pageParam) params.set('cursor', pageParam);
      return request<ProductsPage>(`/shops/${shopId}/products?${params.toString()}`);
    },
    getNextPageParam: (last) => last.next_cursor,
    enabled: !!shopId,
    staleTime: STALE,
  });
}

export function useProduct(shopId: string | null, productId: string, period: string) {
  return useQuery({
    queryKey: ['product', shopId, productId, period],
    queryFn: () => request<ProductDetail>(`/shops/${shopId}/products/${productId}?period=${period}`),
    enabled: !!shopId,
  });
}

// К-24: товар настроен, когда указаны и себестоимость, и остаток. stock_hint — stockCount из прайса продавца.
export type UnconfiguredProduct = {
  product_id: string; sku: string; name: string; category: string;
  needs_cost?: boolean; needs_stock?: boolean; stock_hint?: number | null;
};

export function useMissingCosts(shopId: string | null) {
  return useQuery({
    queryKey: ['missing-costs', shopId],
    queryFn: () => request<{ items: UnconfiguredProduct[] }>(`/shops/${shopId}/products/missing-costs`),
    enabled: !!shopId,
  });
}

export function useCostVersions(shopId: string | null, productId: string) {
  return useQuery({
    queryKey: ['cost-versions', shopId, productId],
    queryFn: () => request<{ items: CostVersion[] }>(`/shops/${shopId}/products/${productId}/cost-versions`),
    enabled: !!shopId,
  });
}

export type CostInput = {
  purchase: string;
  delivery_to_warehouse: string;
  packaging: string;
  other: string;
  apply_to_history: boolean | null;
  effective_from: string | null;
  stock_qty?: number | null;  // К-24: остаток на сейчас — вместе с себестоимостью
};

export function useSaveCost(shopId: string | null, productId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: CostInput) =>
      request<CostVersion>(`/shops/${shopId}/products/${productId}/cost-versions`, { method: 'POST', body }),
    onSuccess: () => invalidateShop(qc, shopId),
  });
}

export function useCancelCost(shopId: string | null) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (versionId: string) =>
      request<{ id: string; cancelled: boolean }>(`/shops/${shopId}/cost-versions/${versionId}/cancel`, { method: 'POST' }),
    onSuccess: () => invalidateShop(qc, shopId),
  });
}

export function useBulkCost(shopId: string | null) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { items: { product_id: string; purchase?: string; stock_qty?: number; delivery_to_warehouse?: string; packaging?: string; other?: string }[]; apply_to_history: boolean }) =>
      request<{ saved: number }>(`/shops/${shopId}/cost-versions/bulk`, { method: 'POST', body }),
    onSuccess: () => invalidateShop(qc, shopId),
  });
}

export function useImportUpload(shopId: string | null) {
  return useMutation({
    mutationFn: (form: FormData) => request<ImportUpload>(`/shops/${shopId}/imports`, { method: 'POST', form }),
  });
}

export function useImportMapping(shopId: string | null) {
  return useMutation({
    mutationFn: ({ importId, mapping, duplicates }: { importId: string; mapping: Record<string, string | null>; duplicates: 'skip' | 'last' }) =>
      request<{ status: string }>(`/shops/${shopId}/imports/${importId}/mapping`, { method: 'PUT', body: { mapping, duplicates } }),
  });
}

export function useImportPreview(shopId: string | null, importId: string | null, enabled: boolean) {
  return useQuery({
    queryKey: ['import-preview', shopId, importId],
    queryFn: () => request<ImportPreview>(`/shops/${shopId}/imports/${importId}/preview`),
    enabled: !!shopId && !!importId && enabled,
    staleTime: 0,
  });
}

export function useImportApply(shopId: string | null) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ importId, applyToHistory }: { importId: string; applyToHistory: boolean | null }) =>
      request<{ status: string; applied_rows: number }>(`/shops/${shopId}/imports/${importId}/apply`, {
        method: 'POST',
        body: { apply_to_history: applyToHistory },
      }),
    onSuccess: () => invalidateShop(qc, shopId),
  });
}

export function useImportUndo(shopId: string | null) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (importId: string) => request<{ status: string }>(`/shops/${shopId}/imports/${importId}/undo`, { method: 'POST' }),
    onSuccess: () => invalidateShop(qc, shopId),
  });
}

export function useCommissions(shopId: string | null) {
  return useQuery({
    queryKey: ['commissions', shopId],
    queryFn: () => request<{ items: Commission[] }>(`/shops/${shopId}/commissions`),
    enabled: !!shopId,
  });
}

export function useSaveCommission(shopId: string | null) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { category: string; rate_percent: string; effective_from: string | null }) =>
      request<{ id: string }>(`/shops/${shopId}/commissions`, { method: 'POST', body }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['commissions', shopId] });
      invalidateShop(qc, shopId);
    },
  });
}

export function useTax(shopId: string | null) {
  return useQuery({
    queryKey: ['tax', shopId],
    queryFn: () => request<TaxSettings>(`/shops/${shopId}/tax`),
    enabled: !!shopId,
  });
}

export function useSaveTax(shopId: string | null) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { enabled: boolean; rate_percent: string | null; effective_from: string | null }) =>
      request<TaxRow>(`/shops/${shopId}/tax`, { method: 'POST', body }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['tax', shopId] });
      invalidateShop(qc, shopId);
    },
  });
}

export function useExpenses(shopId: string | null) {
  return useQuery({
    queryKey: ['expenses', shopId],
    queryFn: () => request<{ items: Expense[] }>(`/shops/${shopId}/expenses`),
    enabled: !!shopId,
  });
}

export function useSaveExpense(shopId: string | null) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { kind: 'ads' | 'other'; amount: string; period_start: string; period_end: string }) =>
      request<{ id: string }>(`/shops/${shopId}/expenses`, { method: 'POST', body }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['expenses', shopId] });
      invalidateShop(qc, shopId);
    },
  });
}

export function useDeleteExpense(shopId: string | null) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => request<void>(`/shops/${shopId}/expenses/${id}`, { method: 'DELETE' }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['expenses', shopId] });
      invalidateShop(qc, shopId);
    },
  });
}

export function useAIQuota(shopId: string | null) {
  return useQuery({
    queryKey: ['ai-quota', shopId],
    queryFn: () => request<AIQuota>(`/ai/quota?shop_id=${shopId}`),
    enabled: !!shopId,
  });
}

export function useAIConsent() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (granted: boolean) =>
      request<{ consent_active: boolean; consent_version: string | null; service: string }>('/ai/consent', {
        method: 'POST',
        body: { granted },
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['ai-quota'] }),
  });
}

export function useAsk(shopId: string | null) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ question, conversationId }: { question: string; conversationId: string | null }) =>
      request<AskAnswer>(`/shops/${shopId}/ai/ask`, {
        method: 'POST',
        body: { question, conversation_id: conversationId },
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['ai-quota'] }),
  });
}

export function useConversations(shopId: string | null, enabled = true) {
  return useQuery({
    queryKey: ['conversations', shopId],
    queryFn: () => request<{ items: Conversation[] }>(`/ai/conversations?shop_id=${shopId}`),
    enabled: !!shopId && enabled,
  });
}

export function useConversation(conversationId: string | null) {
  return useQuery({
    queryKey: ['conversation', conversationId],
    queryFn: () => request<{ id: string; title: string; turns: { id: string; question: string; answer: AskAnswer }[] }>(
      `/ai/conversations/${conversationId}`,
    ),
    enabled: !!conversationId,
  });
}

export function useDeleteConversation(shopId: string | null) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => request<void>(`/ai/conversations/${id}`, { method: 'DELETE' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['conversations', shopId] }),
  });
}

export function useFeedback() {
  return useMutation({
    mutationFn: (body: { shop_id: string; turn_id: string | null; kind: 'up' | 'down' | 'flag'; reason?: string; comment?: string }) =>
      request<{ id: string }>('/ai/feedback', { method: 'POST', body }),
  });
}

export function useReplyDraft(shopId: string | null) {
  return useMutation({
    mutationFn: (body: { question: string; tone: 'polite' | 'short' }) =>
      request<ReplyDraft>(`/ai/reply-drafts?shop_id=${shopId}`, { method: 'POST', body }),
  });
}

export function useProductDraft(shopId: string | null) {
  return useMutation({
    mutationFn: (form: FormData) => request<ProductDraft>('/ai/product-drafts', { method: 'POST', form }),
  });
}

export function useDeleteAccountStart() {
  return useMutation({ mutationFn: () => request<{ status: string }>('/me/deletion/start', { method: 'POST' }) });
}

export function useDeleteAccountConfirm() {
  return useMutation({ mutationFn: (code: string) => request<{ status: string }>('/me/deletion/confirm', { method: 'POST', body: { code } }) });
}

// К-21: деактивация на 30 дней — тот же код из письма, что и для удаления.
export function useDeactivateConfirm() {
  return useMutation({
    mutationFn: (code: string) => request<{ status: string; delete_on: string }>('/me/deactivation/confirm', { method: 'POST', body: { code } }),
  });
}

// К-21: восстановление — сервер проверяет, что подписка оплачена.
export function useReactivate() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => request<{ status: string }>('/me/reactivation', { method: 'POST' }),
    onSuccess: () => { void qc.invalidateQueries(); },
  });
}

export type NotificationPrefs = { product_in_minus: boolean; weekly_summary: boolean; quiet_hours: boolean };

// 3.4: текущие настройки с сервера — экран показывает их, а не «всё выключено»
export function useNotificationSettingsQuery(enabled = true) {
  return useQuery({ queryKey: ['notif'], queryFn: () => request<NotificationPrefs>('/notification-settings'), enabled });
}

export function useNotificationSettings() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: Partial<NotificationPrefs>) =>
      request<NotificationPrefs>('/notification-settings', { method: 'PATCH', body }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['notif'] }),
  });
}

export function useCreateShop() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { name: string; timezone: string; language: 'ru' | 'kk' }) =>
      request<ShopSummary>('/shops', { method: 'POST', body }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['shops'] }),
  });
}

/** К-33 А2: «Я плательщик НДС» — меняет расчёт прибыли (выручка, комиссия и доставка без НДС). */
export function useSetVatPayer(shopId: string | null) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (vat_payer: boolean) =>
      request<ShopSummary>(`/shops/${shopId}`, { method: 'PATCH', body: { vat_payer } }),
    onSuccess: () => qc.invalidateQueries(),
  });
}

/** К-33 А3: себестоимость-пример «≈ N % от цены» в режиме презентации. */
export function useExampleCostPct(shopId: string | null) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (percent: number) =>
      request<{ cost_pct: number }>(`/shops/${shopId}/presentation/cost-percent`, { method: 'POST', body: { percent } }),
    onSuccess: () => qc.invalidateQueries(),
  });
}

export function useResetDemo() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => request<{ shop_id: string }>('/demo/reset', { method: 'POST' }),
    onSuccess: () => qc.invalidateQueries(),
  });
}

/** Обновить все данные магазина после изменения затрат или импорта. */
export function invalidateShop(qc: ReturnType<typeof useQueryClient>, shopId: string | null) {
  qc.invalidateQueries({
    predicate: (q) => Array.isArray(q.queryKey) && q.queryKey[1] === shopId && q.queryKey[0] !== 'ai-quota',
  });
}


// Аккаунт (К-21): номер продавца — 8 цифр, его называют в поддержке.
export type MeView = { email?: string | null; seller_number?: string | null; deactivated?: boolean; delete_on?: string | null;
  onboarding_done?: boolean };

export function useMe(enabled = true) {
  return useQuery({ queryKey: ['me'], queryFn: () => request<MeView>('/me'), enabled });
}

// Подписка (ТЗ 2.1, раздел 8). Состояние хранит сервер.
type SubscriptionView = components['schemas']['SubscriptionOut'];

export function useSubscription(shopId: string | null) {
  return useQuery({
    queryKey: ['subscription', shopId],
    queryFn: () => request<SubscriptionView>(`/shops/${shopId}/subscription`),
    enabled: !!shopId,
  });
}

export type DeviceTrust = components['schemas']['DeviceIn'];
export type SubscriptionOffer = components['schemas']['OfferOut'];
export type PurchaseVerify = components['schemas']['PurchaseVerifyIn'];

export function useStartTrial(shopId: string | null) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (device: DeviceTrust = {}) =>
      request<SubscriptionView>(`/shops/${shopId}/subscription/trial`, { method: 'POST', body: device }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['subscription', shopId] });
      invalidateShop(qc, shopId);
    },
  });
}

// 3.1 (К-21): что покупать — с пробным периодом или без (решает сервер по телефону, магазину Kaspi и аккаунту)
export function useSubscriptionOffer(shopId: string | null) {
  return useMutation({
    mutationFn: (device: DeviceTrust) =>
      request<SubscriptionOffer>(`/shops/${shopId}/subscription/offer`, { method: 'POST', body: device }),
  });
}

// Проверка покупки сервером у App Store / Google Play; тот же вызов — для «Восстановить покупки»
export function useVerifyPurchase(shopId: string | null) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: PurchaseVerify) =>
      request<SubscriptionView>(`/shops/${shopId}/subscription/verify`, { method: 'POST', body }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['subscription', shopId] });
      invalidateShop(qc, shopId);
    },
  });
}

// ---- Склад (решения владельца 22.11): остатки, приход, уведомления, снятие с продажи ----
export type StockItem = {
  productId: string; sku: string; name: string; current: number; baseQty: number; soldSince: number;
  returnedSince: number; avgDaily: number; daysLeft: number | null; level: 'out' | 't3' | 't5' | 't10' | null; delisted: boolean;
  pendingReturns?: number;  // К-26: возвраты без подтверждения «вернулся на склад»
  example?: boolean;  // К-33 А3: остаток — пример (режим презентации)
  returning?: number;  // К-33 А4: отмена после передачи в Kaspi Доставку — едет обратно
  buffer?: number;  // К-33 А4: буфер автоснятия
  forSale?: number;  // К-33 А4: сколько видно в Kaspi (остаток − буфер)
};

export function useStockList(shopId: string | null) {
  return useQuery({
    queryKey: ['stock', shopId],
    queryFn: () => request<{ items: StockItem[] }>(`/shops/${shopId}/stock`),
    enabled: !!shopId,
  });
}

export function useStockAlerts(shopId: string | null) {
  return useQuery({
    queryKey: ['stock-alerts', shopId],
    queryFn: () => request<{ items: StockItem[]; endingSoon: StockItem[] }>(`/shops/${shopId}/stock/alerts`),
    enabled: !!shopId,
  });
}

export function useStockMutations(shopId: string | null) {
  const qc = useQueryClient();
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ['stock', shopId] });
    qc.invalidateQueries({ queryKey: ['stock-alerts', shopId] });
  };
  const receipt = useMutation({
    mutationFn: (v: { productId: string; qty: number }) =>
      request(`/shops/${shopId}/products/${v.productId}/stock/receipt`, { method: 'POST', body: { qty: v.qty } }),
    onSuccess: refresh,
  });
  const inventory = useMutation({
    mutationFn: (v: { productId: string; qty: number }) =>
      request(`/shops/${shopId}/products/${v.productId}/stock`, { method: 'PUT', body: { qty: v.qty } }),
    onSuccess: refresh,
  });
  const delist = useMutation({
    mutationFn: (productId: string) =>
      request(`/shops/${shopId}/products/${productId}/stock/delist`, { method: 'POST', body: { confirm: true } }),
    onSuccess: refresh,
  });
  const relist = useMutation({
    mutationFn: (productId: string) =>
      request(`/shops/${shopId}/products/${productId}/stock/relist`, { method: 'POST' }),
    onSuccess: refresh,
  });
  const confirmReturns = useMutation({
    mutationFn: (v: { productId: string; sellable: boolean }) =>
      request(`/shops/${shopId}/products/${v.productId}/stock/returns`, { method: 'POST', body: { sellable: v.sellable } }),
    onSuccess: refresh,
  });
  // К-33 А4: отмена после передачи в Kaspi Доставку — продавец забрал товар (годен / брак)
  const pickedUp = useMutation({
    mutationFn: (v: { productId: string; qty: number; sellable: boolean }) =>
      request(`/shops/${shopId}/products/${v.productId}/stock/picked-up`, { method: 'POST', body: { qty: v.qty, sellable: v.sellable } }),
    onSuccess: refresh,
  });
  // К-33 А4: буфер автоснятия
  const buffer = useMutation({
    mutationFn: (v: { productId: string; buffer: number }) =>
      request(`/shops/${shopId}/products/${v.productId}/stock/buffer`, { method: 'PUT', body: { buffer: v.buffer } }),
    onSuccess: refresh,
  });
  return { receipt, inventory, delist, relist, confirmReturns, pickedUp, buffer };
}
