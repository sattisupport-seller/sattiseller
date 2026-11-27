import { useRouter } from 'expo-router';
import { useEffect, useState } from 'react';
import { CircleCheck } from 'lucide-react-native';
import { Linking, ScrollView, View } from 'react-native';

import { ApiError } from '@/api/client';
import {
  useAppConfig, useStartTrial, useSubscription, useSubscriptionOffer, useVerifyPurchase,
  type DeviceTrust, type SubscriptionOffer,
} from '@/api/hooks';
import { Button } from '@/components/ui/Button';
import { Card } from '@/components/ui/Surfaces';
import { Txt } from '@/components/ui/Text';
import { ErrorState, Skeleton, useToast } from '@/components/ui/Overlays';
import { trackEvent } from '@/lib/analytics';
import {
  PurchaseCancelled, PurchasesUnavailable, buySubscription, deviceTrust, openManageSubscriptions,
  purchasesAvailable, restorePurchases,
} from '@/lib/purchases';
import { useSession } from '@/session/SessionProvider';
import { useI18n } from '@/i18n';
import { useTheme } from '@/theme/useTheme';

// Экран подписки (ТЗ 2.1, 8.4; MASTER_PLAN 3.1, К-21): цена, период, автопродление, условия и политика,
// «Восстановить покупки», управление подпиской. Доступ выдаёт сервер после проверки покупки у магазина.
export default function PaywallScreen() {
  const { t } = useI18n();
  useEffect(() => { trackEvent('paywall_shown'); }, []);  // 3.9: событие без персональных данных
  const { colors, spacing } = useTheme();
  const router = useRouter();
  const toast = useToast();
  const { shopId } = useSession();
  const config = useAppConfig();
  const sub = useSubscription(shopId);
  const trial = useStartTrial(shopId);
  const offerReq = useSubscriptionOffer(shopId);
  const verify = useVerifyPurchase(shopId);
  const [offer, setOffer] = useState<SubscriptionOffer | null>(null);
  const [device, setDevice] = useState<DeviceTrust>({});
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const storeReady = purchasesAvailable();

  // Что покупать — решает сервер: с пробным периодом или без (телефон, магазин Kaspi, аккаунт).
  const { mutateAsync: loadOffer } = offerReq;
  useEffect(() => {
    if (!storeReady || !shopId) return;
    let alive = true;
    (async () => {
      const d = await deviceTrust();
      if (!alive) return;
      setDevice(d);
      try {
        const o = await loadOffer(d);
        if (alive) setOffer(o);
      } catch {
        // экран останется с данными GET /subscription; ошибка покажется при нажатии
      }
    })();
    return () => { alive = false; };
  }, [storeReady, shopId, loadOffer]);

  if (sub.isLoading) {
    return <View style={{ padding: spacing.lg, gap: spacing.md }}><Skeleton height={120} radius={16} /></View>;
  }
  if (sub.isError || !sub.data) {
    return <ErrorState title={t('common.errorTitle')} body={t('subscription.loadFailed')} onRetry={() => sub.refetch()} />;
  }

  const offerTrial = offer ? offer.trial_available : sub.data.trial_available === true;
  const trialNote = offer && !offer.trial_available && offer.reason_text ? offer.reason_text : null;
  const benefits = [t('subscription.benefit1'), t('subscription.benefit2'), t('subscription.benefit3'), t('subscription.benefit4')];

  const errorText = (e: unknown) => {
    if (e instanceof PurchasesUnavailable) return t('subscription.storeOnlyInApp');
    const code = e instanceof ApiError ? e.code : '';
    if (code === 'store_not_configured') return t('subscription.storeNotConnected');
    if (code === 'trial_used' || code === 'trial_used_device') return t('subscription.trialUsed');
    if (code === 'purchase_other_account') return t('subscription.otherAccount');
    return e instanceof ApiError ? e.message : t('common.unknownError');
  };

  const act = async () => {
    setMessage(null);
    setBusy(true);
    try {
      if (!storeReady) {
        // Expo Go и разработка: пробный период без магазина приложений (только тестовый режим сервера)
        await trial.mutateAsync(device);
        router.back();
        return;
      }
      const current = offer ?? await offerReq.mutateAsync(device);
      setOffer(current);
      const bought = await buySubscription(current, device);
      const result = await verify.mutateAsync(bought.verify);
      await bought.finish();  // закрываем транзакцию только после проверки сервером
      if (result.state === 'trial_denied') {
        setMessage(t('subscription.trialDenied'));
        return;
      }
      router.back();
    } catch (e) {
      if (!(e instanceof PurchaseCancelled)) setMessage(errorText(e));
    } finally {
      setBusy(false);
    }
  };

  const restore = async () => {
    setMessage(null);
    setBusy(true);
    try {
      const ids = offer ?? { apple_product_id: '', google_subscription_id: 'satti_monthly' };
      const found = await restorePurchases(ids, null);
      if (found.length === 0) {
        setMessage(t('subscription.restoreNone'));
        return;
      }
      for (const body of found) await verify.mutateAsync(body);
      toast.show(t('subscription.restored'));
      router.back();
    } catch (e) {
      setMessage(errorText(e));
    } finally {
      setBusy(false);
    }
  };

  const terms = config.data?.terms_url;
  const privacy = config.data?.privacy_url;

  return (
    <ScrollView contentContainerStyle={{ padding: spacing.lg, paddingBottom: 48, gap: spacing.lg }} style={{ backgroundColor: colors.bg }}>
      <Txt variant="title1">{t('subscription.paywallTitle')}</Txt>

      <View style={{ gap: spacing.sm }}>
        {benefits.map((b) => (
          <View key={b} style={{ flexDirection: 'row', gap: spacing.sm, alignItems: 'flex-start' }}>
            <CircleCheck size={20} color={colors.success} />
            <Txt variant="body" style={{ flex: 1 }}>{b}</Txt>
          </View>
        ))}
      </View>

      <Card style={{ gap: spacing.xs }}>
        <Txt variant="title2" numeric>{sub.data.price_text}</Txt>
        <Txt variant="subhead" tone="secondary">{t('subscription.period')}</Txt>
        <Txt variant="subhead" tone="secondary">
          {offerTrial ? t('subscription.trialFirst') : (trialNote ?? t('subscription.trialUsed'))}
        </Txt>
      </Card>

      {sub.data.state === 'trial_denied' ? <Txt variant="footnote" tone="secondary">{t('subscription.trialDenied')}</Txt> : null}
      {message ? <Txt variant="footnote" tone="danger">{message}</Txt> : null}

      <Button
        title={offerTrial ? t('subscription.trialButton') : t('subscription.subscribeButton')}
        onPress={act}
        loading={busy}
        fullWidth
      />
      {offerTrial ? (
        <Txt variant="footnote" tone="tertiary" align="center">{t('subscription.thenPrice', { price: sub.data.price_text })}</Txt>
      ) : null}
      <Txt variant="footnote" tone="tertiary">{t('subscription.autoRenew')}</Txt>

      <View style={{ gap: spacing.xs }}>
        <Button title={t('subscription.restore')} variant="secondary" onPress={restore} disabled={busy} fullWidth />
        <Button title={t('subscription.manage')} variant="text"
                onPress={() => openManageSubscriptions(offer?.google_subscription_id ?? 'satti_monthly')} fullWidth />
        {terms ? <Button title={t('subscription.terms')} variant="text" onPress={() => Linking.openURL(terms)} fullWidth /> : null}
        {privacy ? <Button title={t('subscription.privacy')} variant="text" onPress={() => Linking.openURL(privacy)} fullWidth /> : null}
      </View>
      <Button title={t('subscription.notNow')} variant="text" onPress={() => router.back()} fullWidth />
    </ScrollView>
  );
}
