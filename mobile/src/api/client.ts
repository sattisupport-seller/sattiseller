import { Platform } from 'react-native';
// HTTP-клиент: токены в защищённом хранилище (Keychain / Keystore), обновление сессии, повторы для чтения.
import { deleteItem, getItem, setItem } from '@/lib/storage';

import { API_URL } from '@/config';

import type { ApiErrorBody } from './types';

const KEY_ACCESS = 'satti.access';
const KEY_REFRESH = 'satti.refresh';
const KEY_DEVICE = 'satti.device';
const KEY_SHOP = 'satti.shop';

export class ApiError extends Error {
  status: number;
  code: string;
  constructor(status: number, code: string, message: string) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

type Tokens = { access: string | null; refresh: string | null };
let tokens: Tokens = { access: null, refresh: null };
let onSessionLost: (() => void) | null = null;
let acceptLanguage = 'ru';

// Ошибки приложения на сервер (ТЗ 2.1, 14.4): без персональных данных, сервер маскирует текст.
export function reportClientError(where: string, message: string) {
  fetch(`${API_URL}/telemetry/errors`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ where: where.slice(0, 160), message: message.slice(0, 2000), exc_type: 'ClientError', platform: Platform.OS }),
  }).catch(() => undefined);
}

// Подписка закончилась: сервер отвечает subscription_required (ТЗ 2.1, 9.1). Экран блокировки открывает приложение.
let onSubscriptionRequired: (() => void) | null = null;
export function setSubscriptionRequiredHandler(fn: () => void) {
  onSubscriptionRequired = fn;
}
function notifyError(body: ApiErrorBody | null) {
  if (body?.error.code === 'subscription_required') onSubscriptionRequired?.();
}

export function setSessionLostHandler(fn: () => void) {
  onSessionLost = fn;
}

export function setAcceptLanguage(lang: 'ru' | 'kk') {
  acceptLanguage = lang;
}

export async function loadStoredSession(): Promise<Tokens> {
  try {
    const [access, refresh] = await Promise.all([
      getItem(KEY_ACCESS),
      getItem(KEY_REFRESH),
    ]);
    tokens = { access, refresh };
  } catch {
    tokens = { access: null, refresh: null };
  }
  return tokens;
}

export async function saveTokens(access: string, refresh: string) {
  tokens = { access, refresh };
  await Promise.all([
    setItem(KEY_ACCESS, access),
    setItem(KEY_REFRESH, refresh),
  ]);
}

export async function clearSession() {
  tokens = { access: null, refresh: null };
  await Promise.all([
    deleteItem(KEY_ACCESS),
    deleteItem(KEY_REFRESH),
    deleteItem(KEY_SHOP),
  ]);
}

export function hasSession(): boolean {
  return !!tokens.access || !!tokens.refresh;
}

export async function getDeviceId(): Promise<string> {
  let id = await getItem(KEY_DEVICE);
  if (!id) {
    const bytes = new Uint8Array(16);
    for (let i = 0; i < bytes.length; i++) bytes[i] = Math.floor(Math.random() * 256);
    id = Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('');
    await setItem(KEY_DEVICE, id);
  }
  return id;
}

export async function getStoredShopId(): Promise<string | null> {
  return getItem(KEY_SHOP);
}

export async function setStoredShopId(id: string | null) {
  if (id) await setItem(KEY_SHOP, id);
  else await deleteItem(KEY_SHOP);
}

type Options = {
  method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';
  body?: unknown;
  form?: FormData;
  auth?: boolean;
  retryable?: boolean;
  text?: boolean;
  headers?: Record<string, string>;
};

async function rawRequest(path: string, opts: Options): Promise<Response> {
  const headers: Record<string, string> = {
    'Accept-Language': acceptLanguage,
    Accept: 'application/json',
    ...(opts.headers ?? {}),
  };
  if (opts.auth !== false && tokens.access) headers.Authorization = `Bearer ${tokens.access}`;
  let body: BodyInit | undefined;
  if (opts.form) {
    body = opts.form;
  } else if (opts.body !== undefined) {
    headers['Content-Type'] = 'application/json';
    body = JSON.stringify(opts.body);
  }
  const url = `${API_URL}${path}`;
  const attempts = opts.retryable ? 3 : 1;
  let lastError: unknown = null;
  for (let i = 0; i < attempts; i++) {
    try {
      return await fetch(url, { method: opts.method ?? 'GET', headers, body });
    } catch (e) {
      lastError = e;
      await new Promise((r) => setTimeout(r, 300 * 2 ** i));
    }
  }
  throw new ApiError(0, 'network', String(lastError ?? 'network'));
}

async function refreshTokens(): Promise<boolean> {
  if (!tokens.refresh) return false;
  const res = await fetch(`${API_URL}/auth/refresh`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'Accept-Language': acceptLanguage },
    body: JSON.stringify({ refresh_token: tokens.refresh }),
  });
  if (!res.ok) return false;
  const data = (await res.json()) as { access_token: string; refresh_token: string };
  await saveTokens(data.access_token, data.refresh_token);
  return true;
}

export async function request<T>(path: string, opts: Options = {}): Promise<T> {
  let res = await rawRequest(path, opts);
  if (res.status === 401 && opts.auth !== false) {
    const refreshed = await refreshTokens().catch(() => false);
    if (refreshed) {
      res = await rawRequest(path, opts);
    } else {
      await clearSession();
      onSessionLost?.();
      throw new ApiError(401, 'unauthorized', 'Сессия истекла. Войдите снова.');
    }
  }
  if (!res.ok) {
    let body: ApiErrorBody | null = null;
    try {
      body = (await res.json()) as ApiErrorBody;
    } catch {
      body = null;
    }
    notifyError(body);
    throw new ApiError(res.status, body?.error.code ?? 'http', body?.error.message ?? `HTTP ${res.status}`);
  }
  if (res.status === 204) return undefined as T;
  if (opts.text) return (await res.text()) as unknown as T;
  return (await res.json()) as T;
}

/** Скачивание файла (шаблоны) в виде base64 — для сохранения и отправки через системное меню. */
export async function requestBinary(path: string): Promise<ArrayBuffer> {
  const res = await rawRequest(path, { auth: false });
  if (!res.ok) throw new ApiError(res.status, 'http', `HTTP ${res.status}`);
  return res.arrayBuffer();
}

/** Выгрузки с авторизацией (Excel, «Мои данные»): то же обновление токена, что и в request. */
export async function requestFile(path: string): Promise<ArrayBuffer> {
  let res = await rawRequest(path, {});
  if (res.status === 401) {
    const refreshed = await refreshTokens().catch(() => false);
    if (!refreshed) {
      await clearSession();
      onSessionLost?.();
      throw new ApiError(401, 'unauthorized', 'Сессия истекла. Войдите снова.');
    }
    res = await rawRequest(path, {});
  }
  if (!res.ok) {
    let body: ApiErrorBody | null = null;
    try {
      body = (await res.json()) as ApiErrorBody;
    } catch {
      body = null;
    }
    notifyError(body);
    throw new ApiError(res.status, body?.error.code ?? 'http', body?.error.message ?? `HTTP ${res.status}`);
  }
  return res.arrayBuffer();
}
