// Покупки подписки (MASTER_PLAN 3.1, К-21): expo-iap — App Store (StoreKit 2) и Google Play Billing.
// Нативные модули есть только в сборке приложения (dev build, TestFlight, Google Play). В Expo Go их нет:
// модули загружаются лениво, а экран показывает понятное сообщение вместо падения.
// Доступ выдаёт только сервер: приложение присылает идентификатор покупки, сервер спрашивает магазин.
import Constants from 'expo-constants';
import { Linking, Platform } from 'react-native';

import type { DeviceTrust, PurchaseVerify, SubscriptionOffer } from '@/api/hooks';

type Iap = typeof import('expo-iap');
type IapPurchase = import('expo-iap').Purchase;

export class PurchasesUnavailable extends Error {}
export class PurchaseCancelled extends Error {}

let cached: Iap | null | undefined;

function iap(): Iap | null {
  if (cached !== undefined) return cached;
  try {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    cached = require('expo-iap') as Iap;
  } catch {
    cached = null; // Expo Go или веб: нативного модуля покупок нет
  }
  return cached;
}

export function purchasesAvailable(): boolean {
  return (Platform.OS === 'ios' || Platform.OS === 'android') && iap() !== null;
}

/** Одноразовый токен проверки телефона для правила «пробный период — один на телефон».
 * iPhone — DeviceCheck (локальный модуль SattiDeviceCheck), Android — Play Integrity (@expo/app-integrity).
 * null — проверка недоступна (Expo Go, эмулятор, нет номера проекта Google): сервер пробный период не даст. */
export async function deviceTrust(): Promise<DeviceTrust> {
  try {
    if (Platform.OS === 'ios') {
      // eslint-disable-next-line @typescript-eslint/no-require-imports
      const mod = require('../../modules/satti-device-check') as typeof import('../../modules/satti-device-check');
      const token = await mod.generateTokenAsync();
      return token ? { platform: 'ios', device_token: token } : {};
    }
    if (Platform.OS === 'android') {
      const project = (Constants.expoConfig?.extra as { googleCloudProjectNumber?: string } | undefined)
        ?.googleCloudProjectNumber;
      if (!project) return {};
      // eslint-disable-next-line @typescript-eslint/no-require-imports
      const integrity = require('@expo/app-integrity') as typeof import('@expo/app-integrity');
      await integrity.prepareIntegrityTokenProviderAsync(project);
      const token = await integrity.requestIntegrityCheckAsync(`satti-trial-${Date.now()}`);
      return { platform: 'android', device_token: token };
    }
  } catch {
    // нет модуля или сбой проверки — без токена; сервер запишет причину и не даст пробный период
  }
  return {};
}

function purchaseId(p: IapPurchase): string | null {
  if (Platform.OS === 'ios') return (p as { transactionId?: string | null }).transactionId ?? p.id ?? null; // StoreKit 2
  return (p as { purchaseToken?: string | null }).purchaseToken ?? null;
}

function ourProducts(offer: Pick<SubscriptionOffer, 'apple_product_id' | 'google_subscription_id'>, extra: string[]) {
  return new Set([offer.apple_product_id, offer.google_subscription_id, ...extra]);
}

/** Покупка подписки. Возвращает тело для POST /subscription/verify. */
export async function buySubscription(offer: SubscriptionOffer, device: DeviceTrust): Promise<{
  verify: PurchaseVerify; finish: () => Promise<void>;
}> {
  const lib = iap();
  if (!lib) throw new PurchasesUnavailable();
  await lib.initConnection();
  const done = new Promise<IapPurchase>((resolve, reject) => {
    const ok = lib.purchaseUpdatedListener((p) => { ok.remove(); fail.remove(); resolve(p); });
    const fail = lib.purchaseErrorListener((e) => {
      ok.remove(); fail.remove();
      reject(lib.isUserCancelledError(e) ? new PurchaseCancelled() : new Error(e.message));
    });
  });
  if (Platform.OS === 'ios') {
    await lib.requestPurchase({
      type: 'subs',
      request: { apple: { sku: offer.apple_product_id, appAccountToken: offer.account_token } },
    });
  } else {
    const products = await lib.fetchProducts({ skus: [offer.google_subscription_id], type: 'subs' });
    const product = (products ?? [])[0] as { subscriptionOffers?: { id: string; offerTokenAndroid?: string | null }[] | null } | undefined;
    const offers = product?.subscriptionOffers ?? [];
    // с пробным периодом — предложение trial; без — базовый план (предложение с пробным периодом не показываем)
    const chosen = offer.google_offer_id
      ? offers.find((o) => o.id === offer.google_offer_id)
      : offers.find((o) => o.id !== offer.google_offer_id && !String(o.id).includes('trial'));
    if (!chosen?.offerTokenAndroid) throw new Error('offer_not_found');
    await lib.requestPurchase({
      type: 'subs',
      request: { google: { skus: [offer.google_subscription_id], obfuscatedAccountId: offer.account_token,
                           subscriptionOffers: [{ sku: offer.google_subscription_id, offerToken: chosen.offerTokenAndroid }] } },
    });
  }
  const purchase = await done;
  const id = purchaseId(purchase);
  if (!id) throw new Error('purchase_without_id');
  return {
    verify: { store: Platform.OS === 'ios' ? 'apple' : 'google', purchase_id: id, ...device },
    finish: async () => { await lib.finishTransaction({ purchase, isConsumable: false }); },
  };
}

/** «Восстановить покупки»: все найденные подписки Satti — на проверку сервером. */
export async function restorePurchases(offer: Pick<SubscriptionOffer, 'apple_product_id' | 'google_subscription_id'>,
                                       plainAppleProduct: string | null): Promise<PurchaseVerify[]> {
  const lib = iap();
  if (!lib) throw new PurchasesUnavailable();
  await lib.initConnection();
  await lib.restorePurchases();
  const ours = ourProducts(offer, plainAppleProduct ? [plainAppleProduct] : []);
  const found = (await lib.getAvailablePurchases()) ?? [];
  const out: PurchaseVerify[] = [];
  for (const p of found) {
    const id = purchaseId(p);
    if (id && ours.has(p.productId)) out.push({ store: Platform.OS === 'ios' ? 'apple' : 'google', purchase_id: id });
  }
  return out;
}

/** Управление подпиской в магазине (отмена — только там). */
export async function openManageSubscriptions(googleSubscriptionId: string): Promise<void> {
  const lib = iap();
  try {
    if (lib) {
      await lib.deepLinkToSubscriptions({ skuAndroid: googleSubscriptionId, packageNameAndroid: 'kz.satti.seller' });
      return;
    }
  } catch {
    // ниже — обычная ссылка
  }
  await Linking.openURL(Platform.OS === 'ios'
    ? 'https://apps.apple.com/account/subscriptions'
    : `https://play.google.com/store/account/subscriptions?sku=${googleSubscriptionId}&package=kz.satti.seller`);
}
