// Сессия приложения: вход, демо-режим, магазин, язык и тема. Токены — только в защищённом хранилище.
import { forgetPushToken } from '@/lib/push';
import { deleteItem, getItem, setItem } from '@/lib/storage';
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';

import {
  ApiError,
  clearSession,
  getDeviceId,
  hasSession,
  loadStoredSession,
  request,
  saveTokens,
  setAcceptLanguage,
  setSessionLostHandler,
  setStoredShopId,
  getStoredShopId,
} from '@/api/client';
import type { ShopSummary } from '@/api/types';

export type ThemeMode = 'system' | 'light' | 'dark';
// К-13 (22.11): интерфейс только на русском. Казахский перевод в словаре не подключён (kk.ts оставлен).
export type Locale = 'ru';
type Status = 'loading' | 'signedOut' | 'needsShop' | 'ready';

type SessionValue = {
  status: Status;
  shopId: string | null;
  isDemo: boolean;
  email: string | null;
  locale: Locale;
  themeMode: ThemeMode;
  // 1.19: сервер просит принять обновлённые условия и политику (версия изменилась)
  termsRequired: boolean;
  acceptTerms: () => Promise<void>;
  startDemo: () => Promise<void>;
  requestCode: (email: string) => Promise<void>;
  verifyCode: (email: string, code: string, acceptTerms?: boolean) => Promise<void>;
  signInWithIdToken: (provider: 'apple' | 'google', idToken: string, nonce?: string, acceptTerms?: boolean, authorizationCode?: string) => Promise<void>;
  createShop: (name: string, timezone: string, language: Locale) => Promise<void>;
  selectShop: (id: string) => Promise<void>;
  logout: () => Promise<void>;
  setThemeMode: (m: ThemeMode) => Promise<void>;
  refresh: () => Promise<void>;
};

const Ctx = createContext<SessionValue | null>(null);


async function readPref<T extends string>(key: string, allowed: readonly T[], fallback: T): Promise<T> {
  try {
    const v = await getItem(key);
    return v && (allowed as readonly string[]).includes(v) ? (v as T) : fallback;
  } catch {
    return fallback;
  }
}

export function SessionProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<Status>('loading');
  const [shopId, setShopId] = useState<string | null>(null);
  const [isDemo, setIsDemo] = useState(false);
  const [email, setEmail] = useState<string | null>(null);
  const locale: Locale = 'ru';
  const [themeMode, setThemeModeState] = useState<ThemeMode>('system');
  const [termsRequired, setTermsRequired] = useState(false);

  const resolveShops = useCallback(async () => {
    const [{ items }, me] = await Promise.all([
      request<{ items: ShopSummary[] }>('/shops'),
      request<{ terms_consent_required?: boolean }>('/me'),
    ]);
    setTermsRequired(me.terms_consent_required === true);
    if (items.length === 0) {
      setStatus('needsShop');
      return;
    }
    const stored = await getStoredShopId();
    const chosen = items.find((s) => s.id === stored) ?? items[0];
    setShopId(chosen.id);
    setIsDemo(chosen.is_demo);
    await setStoredShopId(chosen.id);
    setStatus('ready');
  }, []);

  useEffect(() => {
    setSessionLostHandler(() => {
      setShopId(null);
      setStatus('signedOut');
    });
    (async () => {
      const theme = await readPref('satti.theme', ['system', 'light', 'dark'] as const, 'system');
      setAcceptLanguage('ru');
      setThemeModeState(theme);
      await loadStoredSession();
      if (!hasSession()) {
        setStatus('signedOut');
        return;
      }
      try {
        await resolveShops();
      } catch {
        setStatus('signedOut');
      }
    })();
  }, [resolveShops]);

  const startDemo = useCallback(async () => {
    const deviceId = await getDeviceId();
    const res = await request<{ access_token: string; refresh_token: string; shop_id: string }>('/demo/session', {
      method: 'POST',
      auth: false,
      headers: { 'X-Device-Id': deviceId },
    });
    await saveTokens(res.access_token, res.refresh_token);
    await setStoredShopId(res.shop_id);
    setShopId(res.shop_id);
    setIsDemo(true);
    setTermsRequired(false);
    setEmail(null);
    setStatus('ready');
  }, []);

  const requestCode = useCallback(async (address: string) => {
    await request('/auth/email/start', { method: 'POST', auth: false, body: { email: address } });
    setEmail(address);
  }, []);

  const verifyCode = useCallback(async (address: string, code: string, acceptTerms = false) => {
    const res = await request<{ access_token: string; refresh_token: string; needs_shop_setup: boolean }>(
      '/auth/email/verify',
      { method: 'POST', auth: false, body: { email: address, code, accept_terms: acceptTerms } },
    );
    await saveTokens(res.access_token, res.refresh_token);
    setEmail(address);
    setIsDemo(false);
    await resolveShops();
  }, [resolveShops]);

  // Вход через Apple или Google: токен провайдера проверяет сервер (ТЗ 2.1, раздел 5).
  const signInWithIdToken = useCallback(async (provider: 'apple' | 'google', idToken: string, nonce?: string, acceptTerms = false,
    authorizationCode?: string) => {
    const res = await request<{ access_token: string; refresh_token: string; user: { email: string } }>(
      `/auth/${provider}`,
      { method: 'POST', auth: false, body: { id_token: idToken, nonce: nonce ?? null, accept_terms: acceptTerms,
        ...(authorizationCode ? { authorization_code: authorizationCode } : {}) } },
    );
    await saveTokens(res.access_token, res.refresh_token);
    setEmail(res.user.email);
    setIsDemo(false);
    await resolveShops();
  }, [resolveShops]);

  const createShop = useCallback(async (name: string, timezone: string, language: Locale) => {
    const shop = await request<ShopSummary>('/shops', { method: 'POST', body: { name, timezone, language } });
    await setStoredShopId(shop.id);
    setShopId(shop.id);
    setIsDemo(false);
    setStatus('ready');
  }, []);

  const selectShop = useCallback(async (id: string) => {
    await setStoredShopId(id);
    setShopId(id);
  }, []);

  const logout = useCallback(async () => {
    await forgetPushToken();  // 3.4: телефон больше не получает уведомления этого аккаунта
    try {
      await request('/auth/logout', { method: 'POST' });
    } catch {
      // сессия всё равно завершается на устройстве
    }
    await clearSession();
    setShopId(null);
    setEmail(null);
    setIsDemo(false);
    setTermsRequired(false);
    setStatus('signedOut');
  }, []);

  // 1.19: повторное согласие с текущей версией условий и политики.
  const acceptTerms = useCallback(async () => {
    await request('/me/terms', { method: 'POST', body: { accepted: true } });
    setTermsRequired(false);
  }, []);

  const setThemeMode = useCallback(async (m: ThemeMode) => {
    setThemeModeState(m);
    await setItem('satti.theme', m);
  }, []);

  const refresh = useCallback(async () => {
    if (hasSession()) await resolveShops();
  }, [resolveShops]);

  const value = useMemo<SessionValue>(() => ({
    status, shopId, isDemo, email, locale, themeMode, termsRequired, acceptTerms,
    startDemo, requestCode, verifyCode, signInWithIdToken, createShop, selectShop, logout, setThemeMode, refresh,
  }), [status, shopId, isDemo, email, locale, themeMode, termsRequired, acceptTerms, startDemo, requestCode, verifyCode,
    signInWithIdToken, createShop, selectShop, logout, setThemeMode, refresh]);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useSession(): SessionValue {
  const v = useContext(Ctx);
  if (!v) throw new Error('useSession вне SessionProvider');
  return v;
}

export function errorMessage(e: unknown, fallback: string): string {
  if (e instanceof ApiError) return e.message || fallback;
  return fallback;
}
