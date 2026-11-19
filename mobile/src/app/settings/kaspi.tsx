import { ScrollView, View } from 'react-native';
import { Plug } from 'lucide-react-native';

import { useAppConfig } from '@/api/hooks';
import { Badge, Card } from '@/components/ui/Surfaces';
import { Txt } from '@/components/ui/Text';
import { useI18n } from '@/i18n';
import { useTheme } from '@/theme/useTheme';

// Подключение Kaspi за флагом (docs/spec.md, раздел 11): до ответов Kaspi — только заглушка.
export default function KaspiScreen() {
  const { t } = useI18n();
  const { colors, spacing, radii } = useTheme();
  const { data } = useAppConfig();
  const enabled = data?.flags.kaspi_connection ?? false;
  return (
    <ScrollView contentContainerStyle={{ padding: spacing.lg, paddingBottom: 48, gap: spacing.md }} style={{ backgroundColor: colors.bg }}>
      <View style={{ alignItems: 'center', gap: spacing.md, paddingVertical: spacing.xl }}>
        <View style={{ width: 72, height: 72, borderRadius: radii.full, backgroundColor: colors.primarySoft, alignItems: 'center', justifyContent: 'center' }}>
          <Plug size={32} color={colors.onPrimarySoft} />
        </View>
        <Badge label={t('profile.soon')} tone="neutral" />
      </View>
      <Card>
        <Txt variant="body" tone="secondary">{t('settings.kaspiSoon')}</Txt>
      </Card>
      <Card style={{ gap: spacing.sm }}>
        <Txt variant="bodyMedium">{t('settings.kaspiBullet1')}</Txt>
        <Txt variant="bodyMedium">{t('settings.kaspiBullet2')}</Txt>
        <Txt variant="footnote" tone="tertiary">{t('settings.kaspiSoonHint')}</Txt>
      </Card>
      {enabled ? <Txt variant="footnote" tone="tertiary">флаг включён</Txt> : null}
    </ScrollView>
  );
}
