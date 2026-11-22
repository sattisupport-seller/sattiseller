import { useRouter } from 'expo-router';
import { useEffect } from 'react';
import { Linking, ScrollView, View } from 'react-native';

import { useAppConfig, useSubscription } from '@/api/hooks';
import { Button } from '@/components/ui/Button';
import { Card, GroupCard, ListRow } from '@/components/ui/Surfaces';
import { Txt } from '@/components/ui/Text';
import { ErrorState, Skeleton, useToast } from '@/components/ui/Overlays';
import { SUPPORT_EMAIL } from '@/config';
import { trackEvent } from '@/lib/analytics';
import { downloadAndShare } from '@/lib/download';
import { useSession } from '@/session/SessionProvider';
import { useI18n } from '@/i18n';
import { useTheme } from '@/theme/useTheme';

// Экран «Подписка закончилась» (ТЗ 2.1, 9.2): данные сохранены до даты, оформить подписку, выгрузка, поддержка.
export default function SubscriptionEndedScreen() {
  useEffect(() => { trackEvent('lock_screen_shown'); }, []);  // 3.9
  const { t, locale } = useI18n();
  const { colors, spacing } = useTheme();
  const router = useRouter();
  const toast = useToast();
  const { shopId, logout } = useSession();
  const sub = useSubscription(shopId);
  const config = useAppConfig();

  if (sub.isLoading) {
    return <View style={{ padding: spacing.lg, gap: spacing.md }}><Skeleton height={120} radius={16} /></View>;
  }
  if (sub.isError || !sub.data) {
    return <ErrorState title={t('common.errorTitle')} body={t('subscription.loadFailed')} onRetry={() => sub.refetch()} />;
  }

  const date = sub.data.data_delete_on ?? '—';
  const dateText = date === '—' ? date : new Date(`${date}T00:00:00`).toLocaleDateString(locale === 'kk' ? 'kk-KZ' : 'ru-RU');

  return (
    <ScrollView contentContainerStyle={{ padding: spacing.lg, paddingBottom: 48, gap: spacing.lg }} style={{ backgroundColor: colors.bg }}>
      <Card style={{ gap: spacing.sm }}>
        <Txt variant="title1">{t('subscription.endedTitle')}</Txt>
        <Txt variant="body" tone="secondary">{t('subscription.endedText', { date: dateText })}</Txt>
      </Card>

      <Button title={t('subscription.subscribeButton')} onPress={() => router.push('/paywall')} fullWidth />

      <GroupCard>
        <ListRow
          title={t('subscription.exportData')}
          onPress={() => {
            downloadAndShare('/me/export', 'satti-moi-dannye.zip', 'application/zip')
              .catch(() => toast.show(t('common.unknownError')));
          }}
        />
        <ListRow title={t('subscription.support')} onPress={() => { void Linking.openURL(`mailto:${SUPPORT_EMAIL}`); }} />
        <ListRow
          title={t('subscription.privacy')}
          onPress={() => { if (config.data) void Linking.openURL(config.data.privacy_url); }}
        />
        <ListRow
          title={t('subscription.terms')}
          onPress={() => { if (config.data) void Linking.openURL(config.data.terms_url); }}
        />
        <ListRow title={t('profile.logout')} onPress={() => { void logout(); }} />
        <ListRow title={t('subscription.deleteAccount')} onPress={() => router.push('/settings/delete-account')} last />
      </GroupCard>
    </ScrollView>
  );
}
