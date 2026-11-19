import { useState } from 'react';
import { ScrollView, Switch, View } from 'react-native';

import { useNotificationSettings } from '@/api/hooks';
import { Txt } from '@/components/ui/Text';
import { Card, GroupCard } from '@/components/ui/Surfaces';
import { useSession } from '@/session/SessionProvider';
import { useI18n } from '@/i18n';
import { useTheme } from '@/theme/useTheme';

// Уведомления (docs/spec.md, 3.8): настройки сохраняются, отправка push — на этапе B.
export default function NotificationsScreen() {
  const { t } = useI18n();
  const { colors, spacing } = useTheme();
  const { isDemo } = useSession();
  const update = useNotificationSettings();
  const [minus, setMinus] = useState(false);
  const [weekly, setWeekly] = useState(false);
  const [quiet, setQuiet] = useState(false);

  const row = (label: string, value: boolean, onChange: (v: boolean) => void) => (
    <View style={{ flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', minHeight: 56, paddingHorizontal: spacing.lg, paddingVertical: spacing.md }}>
      <Txt variant="bodyMedium" style={{ flex: 1, paddingRight: spacing.md }}>{label}</Txt>
      <Switch
        value={value}
        accessibilityLabel={label}
        trackColor={{ true: colors.primary, false: colors.surfaceAlt }}
        onValueChange={(v) => {
          onChange(v);
          update.mutate({ product_in_minus: label === t('settings.notifMinus') ? v : minus,
            weekly_summary: label === t('settings.notifWeekly') ? v : weekly,
            quiet_hours: label === t('settings.notifQuiet') ? v : quiet });
        }}
      />
    </View>
  );

  return (
    <ScrollView contentContainerStyle={{ padding: spacing.lg, paddingBottom: 48, gap: spacing.md }} style={{ backgroundColor: colors.bg }}>
      <GroupCard>
        {row(t('settings.notifMinus'), minus, setMinus)}
        {row(t('settings.notifWeekly'), weekly, setWeekly)}
        {row(t('settings.notifQuiet'), quiet, setQuiet)}
      </GroupCard>
      <Card>
        <Txt variant="footnote" tone="secondary">{t('settings.notifHint')}</Txt>
        {isDemo ? <Txt variant="footnote" tone="tertiary">{t('settings.notifComing')}</Txt> : null}
      </Card>
    </ScrollView>
  );
}
