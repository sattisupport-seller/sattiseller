// Push-уведомления (MASTER_PLAN 3.4, К-21): разрешение спрашиваем в понятный момент — когда продавец сам включает
// уведомление в настройках, а не при первом запуске. Токен Expo регистрируется на сервере (к аккаунту),
// при выходе — удаляется. Нажатие на уведомление открывает нужный экран и пишет событие notification_opened.
// В Expo Go и на эмуляторе токена может не быть — тогда 'unavailable', приложение работает дальше.
import Constants from 'expo-constants';
import * as Notifications from 'expo-notifications';
import { Platform } from 'react-native';

import { request } from '@/api/client';
import { trackEvent } from '@/lib/analytics';

export type PushResult = 'granted' | 'denied' | 'unavailable';

let registeredToken: string | null = null;

const platform = (): 'ios' | 'android' => (Platform.OS === 'ios' ? 'ios' : 'android');

function projectId(): string | undefined {
  const extra = Constants.expoConfig?.extra as { eas?: { projectId?: string } } | undefined;
  return extra?.eas?.projectId ?? (Constants as unknown as { easConfig?: { projectId?: string } }).easConfig?.projectId;
}

export async function enablePush(): Promise<PushResult> {
  try {
    let { status } = await Notifications.getPermissionsAsync();
    if (status !== 'granted') status = (await Notifications.requestPermissionsAsync()).status;
    if (status !== 'granted') return 'denied';
    const id = projectId();
    const { data } = await Notifications.getExpoPushTokenAsync(id ? { projectId: id } : undefined);
    await request('/devices/push-token', { method: 'POST', body: { token: data, platform: platform() } });
    registeredToken = data;
    return 'granted';
  } catch {
    return 'unavailable';
  }
}

// Выход из аккаунта: телефон больше не получает уведомления этого аккаунта.
export async function forgetPushToken(): Promise<void> {
  const token = registeredToken;
  registeredToken = null;
  if (!token) return;
  try {
    await request('/devices/push-token', { method: 'DELETE', body: { token, platform: platform() } });
  } catch {
    // сервер сам удалит токен, когда Expo сообщит, что устройство больше не зарегистрировано
  }
}

// Куда вести по нажатию: данные уведомления содержат только экран и id товара (без данных покупателей).
export function screenFor(data: Record<string, unknown> | undefined): string | null {
  const screen = data?.screen;
  if (screen === 'stock') return '/stock';
  if (screen === 'overview') return '/';
  if (screen === 'product' && typeof data?.productId === 'string') return `/product/${data.productId}`;
  return null;
}

export function listenForTaps(open: (path: string) => void): () => void {
  try {
    const sub = Notifications.addNotificationResponseReceivedListener((response) => {
      trackEvent('notification_opened');  // 3.9
      const path = screenFor(response.notification.request.content.data as Record<string, unknown>);
      if (path) open(path);
    });
    return () => sub.remove();
  } catch {
    return () => undefined;
  }
}
