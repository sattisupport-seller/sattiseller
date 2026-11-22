// Форматирование для интерфейса (docs/spec.md, раздел 8; docs/design.md, раздел 8).
// Приложение ничего не считает: суммы приходят с сервера в тиынах (целые числа) и здесь только печатаются.

// К-13 (22.11): интерфейс только на русском
export type Locale = 'ru';

const NBSP = ' ';
const MINUS = '−';
const TENGE = '₸';

/** Разряды через неразрывный пробел: 1245300 -> "1 245 300". */
export function groupDigits(n: number): string {
  const s = Math.abs(Math.trunc(n)).toString();
  return s.replace(/\B(?=(\d{3})+(?!\d))/g, NBSP);
}

/** Округление половины от нуля до целых тенге (тиыны -> тенге). */
export function tiynToTengeRounded(minor: number): number {
  const sign = minor < 0 ? -1 : 1;
  return sign * Math.floor((Math.abs(minor) + 50) / 100);
}

export type SignMode = 'none' | 'auto';

/** 1245300 тиынов -> "12 453 ₸"; sign 'auto' ставит «+» для положительных и «−» для отрицательных. */
export function formatMoney(minor: number | null | undefined, sign: SignMode = 'none'): string {
  if (minor === null || minor === undefined) return '—';
  const tenge = tiynToTengeRounded(minor);
  const body = `${groupDigits(tenge)}${NBSP}${TENGE}`;
  if (tenge < 0) return `${MINUS}${body}`;
  if (tenge > 0 && sign === 'auto') return `+${body}`;
  return body;
}

/**
 * Сокращённо для KPI и больших сумм (раздел 8):
 * kpi: от 1 000 000 ₸ — «1,25 млн ₸» (два знака);
 * list: от 10 000 000 ₸ — «12,4 млн ₸» (один знак).
 */
export function formatMoneyShort(minor: number | null | undefined, mode: 'kpi' | 'list', locale: Locale = 'ru'): string {
  if (minor === null || minor === undefined) return '—';
  const tenge = tiynToTengeRounded(minor);
  const abs = Math.abs(tenge);
  const threshold = mode === 'kpi' ? 1_000_000 : 10_000_000;
  if (abs < threshold) return formatMoney(minor);
  const millions = abs / 1_000_000;
  const digits = mode === 'kpi' ? 2 : 1;
  const value = roundHalfUp(millions, digits).toFixed(digits).replace('.', ',');
  const unit = 'млн';
  const sign = tenge < 0 ? MINUS : '';
  return `${sign}${value}${NBSP}${unit}${NBSP}${TENGE}`;
}

function roundHalfUp(x: number, digits: number): number {
  const f = 10 ** digits;
  return Math.floor(x * f + 0.5 + 1e-9) / f;
}

/** Проценты из базисных пунктов: 1280 bp -> "12,8%". sign 'auto' добавляет «+». */
export function formatPercentBp(bp: number | null | undefined, sign: SignMode = 'none'): string {
  if (bp === null || bp === undefined) return '—';
  const tenths = Math.floor((Math.abs(bp) + 5) / 10);
  const text = `${Math.floor(tenths / 10)},${tenths % 10}%`;
  if (bp < 0) return `${MINUS}${text}`;
  if (bp > 0 && sign === 'auto') return `+${text}`;
  return text;
}

/** Проценты из целых процентов с одним знаком: используется для ставок комиссии. */
export function formatRateBp(bp: number): string {
  return formatPercentBp(bp);
}

export type CountNoun = 'orders' | 'products' | 'units';

/** "1 заказ", "3 заказа", "64 заказа"; для казахского — без изменения формы. */
export function formatCount(n: number, noun: CountNoun, locale: Locale = 'ru'): string {
  const value = groupDigits(n);
  if (noun === 'units') return `${value} шт.`;
  const forms: [string, string, string] = noun === 'orders' ? ['заказ', 'заказа', 'заказов'] : ['товар', 'товара', 'товаров'];
  return `${value} ${pluralRu(n, forms)}`;
}

export function pluralRu(n: number, forms: [string, string, string]): string {
  const n10 = n % 10;
  const n100 = n % 100;
  if (n10 === 1 && n100 !== 11) return forms[0];
  if (n10 >= 2 && n10 <= 4 && (n100 < 12 || n100 > 14)) return forms[1];
  return forms[2];
}

const MONTHS_RU_SHORT = ['янв.', 'февр.', 'мар.', 'апр.', 'мая', 'июн.', 'июл.', 'авг.', 'сент.', 'окт.', 'нояб.', 'дек.'];

function parseIsoDate(iso: string): { y: number; m: number; d: number } {
  const [y, m, d] = iso.split('-').map(Number);
  return { y, m, d };
}

/** "сегодня", "вчера", "17 нояб.", "17 нояб. 2025" (если год не текущий). */
export function formatDayLabel(iso: string, todayIso: string, locale: Locale = 'ru', yesterdayIso?: string): string {
  if (iso === todayIso) return 'сегодня';
  if (yesterdayIso && iso === yesterdayIso) return 'вчера';
  const { y, m, d } = parseIsoDate(iso);
  const months = MONTHS_RU_SHORT;
  const currentYear = parseIsoDate(todayIso).y;
  const base = `${d} ${months[m - 1]}`;
  return y === currentYear ? base : `${base} ${y}`;
}

/** "6–19 нояб.", "23 окт. – 5 нояб." */
export function formatPeriodRange(fromIso: string, toIso: string, locale: Locale = 'ru'): string {
  const a = parseIsoDate(fromIso);
  const b = parseIsoDate(toIso);
  const months = MONTHS_RU_SHORT;
  if (fromIso === toIso) return `${b.d} ${months[b.m - 1]}`;
  if (a.m === b.m && a.y === b.y) return `${a.d}–${b.d} ${months[b.m - 1]}`;
  return `${a.d} ${months[a.m - 1]} – ${b.d} ${months[b.m - 1]}`;
}

/** Время 24-часовое: "15:40". Принимает ISO-строку с часовым поясом магазина. */
export function formatTime(iso: string): string {
  const m = iso.match(/T(\d{2}):(\d{2})/);
  return m ? `${m[1]}:${m[2]}` : '';
}

/** Время в часовом поясе Алматы (UTC+5, без перехода на летнее время с 2024 года). */
export function formatTimeAlmaty(iso: string): string {
  const ms = Date.parse(iso);
  if (Number.isNaN(ms)) return '';
  const d = new Date(ms + 5 * 3600_000);
  return `${String(d.getUTCHours()).padStart(2, '0')}:${String(d.getUTCMinutes()).padStart(2, '0')}`;
}

/** Дата (YYYY-MM-DD) в часовом поясе Алматы. */
export function todayAlmaty(now: Date = new Date()): string {
  return new Date(now.getTime() + 5 * 3600_000).toISOString().slice(0, 10);
}

/** "№ 584120331" — без разделения на разряды. */
export function formatOrderNumber(number: string): string {
  return `№ ${number}`;
}

export function formatDateTime(iso: string, todayIso: string, locale: Locale = 'ru'): string {
  const day = iso.slice(0, 10);
  return `${formatDayLabel(day, todayIso, locale)}, ${formatTime(iso)}`;
}

/** Для VoiceOver: сумма полностью словами не нужна — даём число и «тенге». */
export function accessibleMoney(minor: number | null | undefined): string {
  if (minor === null || minor === undefined) return 'нет данных';
  const tenge = tiynToTengeRounded(minor);
  return `${tenge < 0 ? 'минус ' : ''}${groupDigits(tenge).replace(/ /g, ' ')} тенге`;
}

/** Проверка ввода денег: цифры, пробелы, одна запятая или точка, до двух знаков. */
export function isMoneyInput(text: string): boolean {
  return /^\d{0,9}([.,]\d{0,2})?$/.test(text.replace(/[\s ]/g, ''));
}
