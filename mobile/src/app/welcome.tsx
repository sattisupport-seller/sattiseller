import { useRouter } from 'expo-router';
import { useState } from 'react';
import { View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Mail, TrendingUp } from 'lucide-react-native';

import { Button } from '@/components/ui/Button';
import { Txt } from '@/components/ui/Text';
import { errorMessage, useSession } from '@/session/SessionProvider';
import { useI18n } from '@/i18n';
import { useTheme } from '@/theme/useTheme';
import { Card } from '@/components/ui/Surfaces';
import { formatMoney } from '@/lib/format';

export default function Welcome() {
  const router = useRouter();
  const { t } = useI18n();
  const { colors, spacing, radii } = useTheme();
  const { startDemo } = useSession();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const tryDemo = async () => {
    setBusy(true);
    setError(null);
    try {
      await startDemo();
      router.replace('/(tabs)');
    } catch (e) {
      setError(errorMessage(e, t('common.networkError')));
    } finally {
      setBusy(false);
    }
  };

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: colors.bg }} edges={['top', 'bottom']}>
      <View style={{ flex: 1, padding: spacing.lg, justifyContent: 'space-between' }}>
        <View style={{ flex: 1, justifyContent: 'center', gap: spacing['2xl'] }}>
          <View style={{ width: 280, alignSelf: 'center', gap: 8 }}>
            <Card style={{ padding: spacing.lg, borderRadius: radii.xl, shadowColor: '#101828', shadowOpacity: 0.12, shadowRadius: 24, shadowOffset: { width: 0, height: 8 } }}>
              <Txt variant="subhead" tone="secondary">{t('overview.segProfit')}</Txt>
              <Txt variant="kpi" numeric style={{ marginTop: 4 }}>{formatMoney(18240000, 'auto')}</Txt>
              <View style={{ marginTop: spacing.md, height: 4, borderRadius: radii.full, backgroundColor: colors.primarySoft, overflow: 'hidden' }}>
                <View style={{ width: '70%', height: 4, backgroundColor: colors.primary }} />
              </View>
            </Card>
            <Card style={{ padding: spacing.md, flexDirection: 'row', alignItems: 'center', gap: spacing.sm, marginLeft: 120 }}>
              <TrendingUp size={20} color={colors.primary} />
              <Txt variant="footnoteStrong">10 товаров без закупки</Txt>
            </Card>
          </View>
          <View style={{ gap: spacing.md }}>
            <Txt variant="display" accessibilityRole="header">{t('welcome.headline')}</Txt>
            <Txt variant="body" tone="secondary">{t('welcome.body')}</Txt>
          </View>
        </View>

        <View style={{ gap: spacing.md }}>
          {error ? <Txt variant="footnote" tone="danger" align="center">{error}</Txt> : null}
          <Button title={t('welcome.tryDemo')} onPress={tryDemo} loading={busy} fullWidth />
          <Button title={t('welcome.loginEmail')} onPress={() => router.push('/login')} variant="secondary" fullWidth
            icon={<Mail size={20} color={colors.onPrimarySoft} />} />
          <Txt variant="footnote" tone="tertiary" align="center">{t('welcome.legal')}</Txt>
          <Txt variant="footnote" tone="tertiary" align="center">{t('welcome.independent')}</Txt>
        </View>
      </View>
    </SafeAreaView>
  );
}
