import { useRouter } from 'expo-router';
import { View } from 'react-native';

import { ApiError } from '@/api/client';
import { useExampleCostPct } from '@/api/hooks';
import { Button } from '@/components/ui/Button';
import { Card, Chip } from '@/components/ui/Surfaces';
import { useToast } from '@/components/ui/Overlays';
import { Txt } from '@/components/ui/Text';
import { useI18n } from '@/i18n';
import { useTheme } from '@/theme/useTheme';

const PERCENTS = [40, 50, 60, 70];

// К-33 А3: режим презентации (включает владелец в админке). Остатки и себестоимость — пример на товарах продавца;
// «≈ N % от цены» меняется прямо на встрече. В магазине Kaspi ничего не меняется.
export function PresentationCard({ shopId, pct }: { shopId: string | null; pct: number }) {
  const { t } = useI18n();
  const { spacing } = useTheme();
  const router = useRouter();
  const toast = useToast();
  const setPct = useExampleCostPct(shopId);

  const choose = async (p: number) => {
    try {
      await setPct.mutateAsync(p);
      toast.show(t('presentation.saved', { pct: p }));
    } catch (e) {
      toast.show(e instanceof ApiError ? e.message : t('common.unknownError'));
    }
  };

  return (
    <Card style={{ gap: spacing.sm, marginTop: spacing.md }}>
      <Txt variant="headline">{t('presentation.title')}</Txt>
      <Txt variant="footnote" tone="secondary">{t('presentation.body')}</Txt>
      <Txt variant="subheadMedium" tone="secondary">{t('presentation.costPct', { pct })}</Txt>
      <View style={{ flexDirection: 'row', flexWrap: 'wrap' }}>
        {PERCENTS.map((p) => (
          <Chip key={p} label={`${p} %`} selected={p === pct} onPress={() => choose(p)} />
        ))}
      </View>
      <Button title={t('presentation.stock')} variant="secondary" onPress={() => router.push('/stock')} fullWidth />
    </Card>
  );
}
