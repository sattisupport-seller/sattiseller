import { useRouter } from 'expo-router';
import { useEffect, useState } from 'react';
import { CircleCheck } from 'lucide-react-native';
import { ScrollView, View } from 'react-native';

import { ApiError } from '@/api/client';
import { useStartTrial, useSubscription } from '@/api/hooks';
import { Button } from '@/components/ui/Button';
import { Card } from '@/components/ui/Surfaces';
import { Txt } from '@/components/ui/Text';
import { ErrorState, Skeleton } from '@/components/ui/Overlays';
import { trackEvent } from '@/lib/analytics';
import { useSession } from '@/session/SessionProvider';
import { useI18n } from '@/i18n';
import { useTheme } from '@/theme/useTheme';

// Экран оплаты (ТЗ 2.1, 8.4). Покупок пока нет: кнопка идёт на сервер, а тот отвечает заглушкой магазина.
export default function PaywallScreen() {
  const { t } = useI18n();
  useEffect(() => { trackEvent('paywall_shown'); }, []);  // 3.9: событие без персональных данных
  const { colors, spacing } = useTheme();
  const router = useRouter();
  const { shopId } = useSession();
  const sub = useSubscription(shopId);
  const trial = useStartTrial(shopId);
  const [message, setMessage] = useState<string | null>(null);

  if (sub.isLoading) {
    return <View style={{ padding: spacing.lg, gap: spacing.md }}><Skeleton height={120} radius={16} /></View>;
  }
  if (sub.isError || !sub.data) {
    return <ErrorState title={t('common.errorTitle')} body={t('subscription.loadFailed')} onRetry={() => sub.refetch()} />;
  }

  const offerTrial = sub.data.trial_available === true;
  const benefits = [t('subscription.benefit1'), t('subscription.benefit2'), t('subscription.benefit3'), t('subscription.benefit4')];

  const act = async () => {
    setMessage(null);
    try {
      await trial.mutateAsync();
      router.back();
    } catch (e) {
      const code = e instanceof ApiError ? e.code : '';
      if (code === 'store_not_configured') setMessage(t('subscription.storeNotConnected'));
      else if (code === 'trial_used') setMessage(t('subscription.trialUsed'));
      else setMessage(e instanceof ApiError ? e.message : t('common.unknownError'));
    }
  };

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
        <Txt variant="subhead" tone="secondary">
          {offerTrial ? t('subscription.trialFirst') : t('subscription.trialUsed')}
        </Txt>
      </Card>

      {message ? <Txt variant="footnote" tone="danger">{message}</Txt> : null}

      <Button
        title={offerTrial ? t('subscription.trialButton') : t('subscription.subscribeButton')}
        onPress={act}
        loading={trial.isPending}
        fullWidth
      />
      {offerTrial ? (
        <Txt variant="footnote" tone="tertiary" align="center">{t('subscription.thenPrice', { price: sub.data.price_text })}</Txt>
      ) : null}
      <Txt variant="footnote" tone="tertiary">{t('subscription.autoRenew')}</Txt>
      <Button title={t('subscription.notNow')} variant="text" onPress={() => router.back()} fullWidth />
    </ScrollView>
  );
}
