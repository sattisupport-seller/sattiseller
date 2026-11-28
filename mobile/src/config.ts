// Адрес сервера задаётся профилем сборки (docs/spec.md, раздел 4.5). Секретов в приложении нет.
// Для разработки на телефоне укажите IP компьютера в локальной сети: EXPO_PUBLIC_API_URL=http://192.168.0.10:8000/v1

/** QA-09: в релизной сборке адрес сервера — только https и без заглушек. Иначе — понятная ошибка, не тихий localhost. */
export function checkApiUrl(url: string, isDev: boolean): string {
  if (isDev) return url;
  if (!url.startsWith('https://')) {
    throw new Error('Релизная сборка требует адрес сервера с https://. Проверьте EXPO_PUBLIC_API_URL в профиле сборки.');
  }
  if (url.includes('REPLACE')) {
    throw new Error('В профиле сборки остался адрес-заглушка. Укажите адрес продакшен-сервера.');
  }
  return url;
}

/**
 * К-33 А0: в разработке без EXPO_PUBLIC_API_URL адрес сервера берётся из адреса Metro (hostUri «172.20.10.2:8081»):
 * тот же компьютер, порт 8000. Сменилась точка доступа — перезапускать с новым адресом не нужно.
 */
export function apiUrlFromHostUri(hostUri: string | null | undefined, port = 8000): string | null {
  if (!hostUri) return null;
  const host = hostUri.replace(/^[a-z]+:\/\//i, '').split('/')[0].replace(/:\d+$/, '');
  if (!host) return null;
  return `http://${host}:${port}/v1`;
}

function metroHostUri(): string | null {
  try {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const Constants = require('expo-constants').default;
    return Constants?.expoConfig?.hostUri ?? null;
  } catch {
    return null;
  }
}

export const API_URL: string = checkApiUrl(
  process.env.EXPO_PUBLIC_API_URL ?? (__DEV__ ? apiUrlFromHostUri(metroHostUri()) : null) ?? 'http://localhost:8000/v1',
  __DEV__,
);

// К-35 п.4 (решение владельца 28.11.2026): почта поддержки и жалоб. Задаётся только здесь (сервер — SATTI_SUPPORT_EMAIL).
export const SUPPORT_EMAIL = 'satti.support@gmail.com';
export const SUPPORT_SUBJECT = 'Satti Seller — обращение';

/** Письмо в поддержку: тема и в тексте — номер продавца (если есть) и версия приложения. */
export function supportMailto(sellerNumber?: string | null, appVersion?: string | null): string {
  if (appVersion == null) {
    try {
      // eslint-disable-next-line @typescript-eslint/no-require-imports
      appVersion = (require('expo-constants').default?.expoConfig?.version as string | undefined) ?? null;
    } catch {
      appVersion = null;
    }
  }
  const lines =['', '', '—', `Номер продавца: ${sellerNumber || 'нет (демо или магазин не подключён)'}`,
    `Версия приложения: ${appVersion || 'неизвестна'}`];
  return `mailto:${SUPPORT_EMAIL}?subject=${encodeURIComponent(SUPPORT_SUBJECT)}&body=${encodeURIComponent(lines.join('\n'))}`;
}
