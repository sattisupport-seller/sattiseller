// Адрес сервера задаётся профилем сборки (docs/spec.md, раздел 4.5). Секретов в приложении нет.
// Для разработки на телефоне укажите IP компьютера в локальной сети: EXPO_PUBLIC_API_URL=http://192.168.0.10:8000/v1
export const API_URL: string = process.env.EXPO_PUBLIC_API_URL ?? 'http://localhost:8000/v1';

export const SUPPORT_EMAIL = 'support@example.invalid';
