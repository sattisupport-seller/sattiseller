// События использования (3.9). Отправляются только имена событий, пакетами; без персональных данных.
// Включаются флагом с сервера (flags.analytics), по умолчанию выключены. Политика конфиденциальности
// должна описать счётчики до включения (docs/legal-proposals.md).
import { request } from '@/api/client';

export const ANALYTICS_EVENTS = [
  'paywall_shown', 'lock_screen_shown', 'restore_tapped', 'trial_started', 'subscription_started',
  'data_export_requested', 'excel_exported', 'tax_rate_saved', 'notification_opened',
  'kaspi_connect_started', 'kaspi_connect_succeeded', 'kaspi_connect_failed',
] as const;
export type AnalyticsEvent = (typeof ANALYTICS_EVENTS)[number];

const BATCH_SIZE = 20;
const FLUSH_INTERVAL_MS = 60_000;
const QUEUE_LIMIT = 200;

let enabled = false;
let queue: AnalyticsEvent[] = [];
let timer: ReturnType<typeof setInterval> | null = null;

export function setAnalyticsEnabled(on: boolean): void {
  enabled = on;
  if (on && !timer) {
    timer = setInterval(() => { void flushAnalytics(); }, FLUSH_INTERVAL_MS);
  }
  if (!on) {
    if (timer) clearInterval(timer);
    timer = null;
    queue = [];
  }
}

export function trackEvent(event: AnalyticsEvent): void {
  if (!enabled) return;
  if (queue.length >= QUEUE_LIMIT) queue.shift();  // очередь не растёт без предела
  queue.push(event);
  if (queue.length >= BATCH_SIZE) void flushAnalytics();
}

export async function flushAnalytics(): Promise<void> {
  if (!enabled || queue.length === 0) return;
  const batch = queue.slice(0, BATCH_SIZE);
  queue = queue.slice(batch.length);
  try {
    await request('/analytics/batch', { method: 'POST', auth: false, body: { events: batch } });
  } catch {
    // события не повторяем: потеря нескольких счётчиков допустима, данные при этом не персональные
  }
}

// для тестов
export function _analyticsState() {
  return { enabled, queued: queue.length };
}
