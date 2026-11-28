import { useRouter } from 'expo-router';
import { useState } from 'react';
import { Linking, ScrollView } from 'react-native';

import { ApiError } from '@/api/client';
import { useMe, useReactivate } from '@/api/hooks';
import { Button } from '@/components/ui/Button';
import { Banner, Card, GroupCard, ListRow } from '@/components/ui/Surfaces';
import { Txt } from '@/components/ui/Text';
import { useToast } from '@/components/ui/Overlays';
import { SUPPORT_EMAIL, supportMailto } from '@/config';
import { openManageSubscriptions } from '@/lib/purchases';
import { useSession } from '@/session/SessionProvider';
import { useI18n } from '@/i18n';
import { useTheme } from '@/theme/useTheme';

// Аккаунт деактивирован (К-21): после входа — только этот экран. Дата удаления, восстановление с оплаченной
// подпиской (сервер проверяет покупку у магазина), полное удаление, выход.
export default function AccountDeactivatedScreen() {
  const { t } = useI18n();
  const { colors, spacing } = useTheme();
  const router = useRouter();
  const toast = useToast();
  const { logout } = useSession();
  const me = useMe();
  const reactivate = useReactivate();
  const [message, setMessage] = useState<string | null>(null);
  const date = me.data?.delete_on ? new Date(me.data.delete_on).toLocaleDateString('ru-RU') : '—';

  const restore = async () => {
    setMessage(null);
    try {
      await reactivate.mutateAsync();
      toast.show(t('deactivated.restored'));
      router.replace('/');
    } catch (e) {
      setMessage(e instanceof ApiError && e.code === 'subscription_required'
        ? t('deactivated.needSubscription')
        : e instanceof ApiError ? e.message : t('common.unknownError'));
    }
  };

  return (
    <ScrollView contentContainerStyle={{ padding: spacing.lg, paddingTop: 64, paddingBottom: 48, gap: spacing.lg }} style={{ backgroundColor: colors.bg }}>
      <Card style={{ gap: spacing.sm }}>
        <Txt variant="title1" accessibilityRole="header">{t('deactivated.title')}</Txt>
        <Txt variant="body" tone="secondary">{t('deactivated.text', { date })}</Txt>
      </Card>
      <Txt variant="subhead" tone="secondary">{t('deactivated.restoreNote')}</Txt>
      {message ? <Banner text={message} tone="warning" /> : null}
      <Button title={t('deactivated.restore')} onPress={restore} loading={reactivate.isPending} fullWidth />
      <Button title={t('deactivated.subscribe')} variant="secondary" onPress={() => router.push('/paywall')} fullWidth />
      <GroupCard>
        <ListRow title={t('subscription.manage')} onPress={() => { void openManageSubscriptions('satti_monthly'); }} />
        <ListRow title={t('subscription.support')} onPress={() => { void Linking.openURL(supportMailto()); }} />
        <ListRow title={t('profile.logout')} onPress={() => { void logout(); }} />
        <ListRow title={t('subscription.deleteAccount')} onPress={() => router.push('/settings/delete-account')} last />
      </GroupCard>
    </ScrollView>
  );
}
