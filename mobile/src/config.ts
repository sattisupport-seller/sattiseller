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

export const API_URL: string = checkApiUrl(
  process.env.EXPO_PUBLIC_API_URL ?? 'http://localhost:8000/v1',
  __DEV__,
);

export const SUPPORT_EMAIL = 'support@example.invalid';
