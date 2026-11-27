import { useRouter } from 'expo-router';
import { Linking, ScrollView } from 'react-native';

import { Card, GroupCard, ListRow } from '@/components/ui/Surfaces';
import { Txt } from '@/components/ui/Text';
import { SUPPORT_EMAIL } from '@/config';
import { openManageSubscriptions } from '@/lib/purchases';
import { useSession } from '@/session/SessionProvider';
import { useI18n } from '@/i18n';
import { useTheme } from '@/theme/useTheme';

// Аккаунт заблокирован владельцем через админку (К-21, решение владельца 01:39): понятное сообщение,
// контакт поддержки, управление подпиской (сама она в магазине не отменяется) и удаление — оно доступно всегда.
export default function AccountBlockedScreen() {
  const { t } = useI18n();
  const { colors, spacing } = useTheme();
  const router = useRouter();
  const { logout } = useSession();

  return (
    <ScrollView contentContainerStyle={{ padding: spacing.lg, paddingTop: 64, paddingBottom: 48, gap: spacing.lg }} style={{ backgroundColor: colors.bg }}>
      <Card style={{ gap: spacing.sm }}>
        <Txt variant="title1" accessibilityRole="header">{t('blocked.title')}</Txt>
        <Txt variant="body" tone="secondary">{t('blocked.text')}</Txt>
        <Txt variant="subhead" tone="secondary" selectable>{t('blocked.contact', { email: SUPPORT_EMAIL })}</Txt>
      </Card>
      <GroupCard>
        <ListRow title={t('subscription.support')} onPress={() => { void Linking.openURL(`mailto:${SUPPORT_EMAIL}`); }} />
        <ListRow title={t('subscription.manage')} onPress={() => { void openManageSubscriptions('satti_monthly'); }} />
        <ListRow title={t('profile.logout')} onPress={() => { void logout(); }} />
        <ListRow title={t('subscription.deleteAccount')} onPress={() => router.push('/settings/delete-account')} last />
      </GroupCard>
      <Txt variant="footnote" tone="tertiary">{t('blocked.subscriptionNote')}</Txt>
    </ScrollView>
  );
}
