import { ScrollView, View } from 'react-native';

import { Card } from '@/components/ui/Surfaces';
import { Txt } from '@/components/ui/Text';
import { useI18n } from '@/i18n';
import { useTheme } from '@/theme/useTheme';
import { formatMoney, formatPercentBp } from '@/lib/format';

// Статья «Как считается прибыль» (docs/spec.md, 12.23): формула и пример на цифрах товара G001.
export default function HowProfitScreen() {
  const { t } = useI18n();
  const { colors, spacing } = useTheme();
  return (
    <ScrollView contentContainerStyle={{ padding: spacing.lg, paddingBottom: 48, gap: spacing.md }} style={{ backgroundColor: colors.bg }}>
      <Card style={{ gap: spacing.sm }}>
        <Txt variant="body">{t('settings.howBody')}</Txt>
      </Card>
      <Card style={{ gap: spacing.sm }}>
        <Txt variant="headline">Пример</Txt>
        <Line label="Выручка (2 × 2 000 ₸)" value={formatMoney(400000)} />
        <Line label="Себестоимость (2 × 1 000 ₸)" value={formatMoney(-200000)} />
        <Line label={`Комиссия ${formatPercentBp(1000)}`} value={formatMoney(-40000)} />
        <Line label="Доставка покупателю (2 × 100 ₸)" value={formatMoney(-20000)} />
        <View style={{ height: 1, backgroundColor: colors.divider }} />
        <Line label="Прибыль" value={formatMoney(140000, 'auto')} strong />
      </Card>
      <Txt variant="footnote" tone="tertiary">Satti Seller — независимый сервис, не связан с Kaspi.kz</Txt>
    </ScrollView>
  );
}

function Line({ label, value, strong }: { label: string; value: string; strong?: boolean }) {
  return (
    <View style={{ flexDirection: 'row', justifyContent: 'space-between' }}>
      <Txt variant={strong ? 'headline' : 'subhead'} tone={strong ? 'primary' : 'secondary'}>{label}</Txt>
      <Txt variant={strong ? 'headline' : 'bodyMedium'} numeric>{value}</Txt>
    </View>
  );
}
