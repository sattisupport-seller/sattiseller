import { useEffect, useState } from 'react';
import { Linking, ScrollView, Switch, View } from 'react-native';

import { useNotificationSettings, useNotificationSettingsQuery, type NotificationPrefs } from '@/api/hooks';
import { Button } from '@/components/ui/Button';
import { Txt } from '@/components/ui/Text';
import { Banner, Card, GroupCard } from '@/components/ui/Surfaces';
import { enablePush } from '@/lib/push';
import { useSession } from '@/session/SessionProvider';
import { useI18n } from '@/i18n';
import { useTheme } from '@/theme/useTheme';

type Key = keyof NotificationPrefs;

// Уведомления (docs/spec.md, 3.8; MASTER_PLAN 3.4): настройки читаются с сервера, меняется только нажатый пункт.
// Разрешение на уведомления спрашиваем, когда продавец включает пункт, — понятный момент, а не первый запуск.
export default function NotificationsScreen() {
  const { t } = useI18n();
  const { colors, spacing } = useTheme();
  const { isDemo } = useSession();
  const current = useNotificationSettingsQuery(!isDemo);
  const update = useNotificationSettings();
  const [prefs, setPrefs] = useState<NotificationPrefs>({ product_in_minus: false, weekly_summary: false, quiet_hours: false });
  const [denied, setDenied] = useState(false);

  // зависимость — сами значения, а не объект ответа: иначе новый объект при каждой отрисовке даёт цикл
  const loaded = current.data;
  const [m, w, q] = [loaded?.product_in_minus, loaded?.weekly_summary, loaded?.quiet_hours];
  useEffect(() => {
    if (m !== undefined && w !== undefined && q !== undefined) setPrefs({ product_in_minus: m, weekly_summary: w, quiet_hours: q });
  }, [m, w, q]);

  const change = async (key: Key, value: boolean) => {
    setPrefs((p) => ({ ...p, [key]: value }));
    update.mutate({ [key]: value });
    if (value && key !== 'quiet_hours') {
      const result = await enablePush();
      setDenied(result === 'denied');
    }
  };

  const row = (key: Key, label: string) => (
    <View style={{ flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', minHeight: 56,
      paddingHorizontal: spacing.lg, paddingVertical: spacing.md }}>
      <Txt variant="bodyMedium" style={{ flex: 1, paddingRight: spacing.md }}>{label}</Txt>
      <Switch
        value={prefs[key]}
        accessibilityLabel={label}
        disabled={isDemo}
        trackColor={{ true: colors.primary, false: colors.surfaceAlt }}
        onValueChange={(v) => { void change(key, v); }}
      />
    </View>
  );

  return (
    <ScrollView contentContainerStyle={{ padding: spacing.lg, paddingBottom: 48, gap: spacing.md }} style={{ backgroundColor: colors.bg }}>
      <GroupCard>
        {row('product_in_minus', t('settings.notifMinus'))}
        {row('weekly_summary', t('settings.notifWeekly'))}
        {row('quiet_hours', t('settings.notifQuiet'))}
      </GroupCard>
      {denied ? (
        <>
          <Banner text={t('settings.notifDenied')} tone="warning" />
          <Button title={t('settings.notifOpenSettings')} variant="secondary" onPress={() => { void Linking.openSettings(); }} fullWidth />
        </>
      ) : null}
      <Card style={{ gap: spacing.xs }}>
        <Txt variant="footnote" tone="secondary">{t('settings.notifHint')}</Txt>
        <Txt variant="footnote" tone="secondary">{t('settings.notifStock')}</Txt>
        {isDemo ? <Txt variant="footnote" tone="tertiary">{t('settings.notifDemo')}</Txt> : null}
      </Card>
    </ScrollView>
  );
}
