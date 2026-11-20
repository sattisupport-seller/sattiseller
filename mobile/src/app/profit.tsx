import { useLocalSearchParams } from 'expo-router';
import { useState } from 'react';
import { ScrollView, View } from 'react-native';

import { useProducts, useProfitBreakdown } from '@/api/hooks';
import { Button } from '@/components/ui/Button';
import { CoverageBar, Card, GroupCard, ListRow, Section } from '@/components/ui/Surfaces';
import { EmptyState, ErrorState, Skeleton, useToast } from '@/components/ui/Overlays';
import { downloadAndShare } from '@/lib/download';
import { Txt } from '@/components/ui/Text';
import { useSession } from '@/session/SessionProvider';
import { useI18n } from '@/i18n';
import { useTheme } from '@/theme/useTheme';
import { formatMoney, formatPercentBp } from '@/lib/format';
import { useRouter } from 'expo-router';

// Лесенка прибыли (docs/design.md, 12.5): продажи → расходы → прибыль по товарам → расходы магазина → прибыль магазина.
export default function ProfitScreen() {
  const { t } = useI18n();
  const { colors, spacing, radii } = useTheme();
  const router = useRouter();
  const { period = '7d' } = useLocalSearchParams<{ period?: string }>();
  const { shopId } = useSession();
  const { data, isLoading, isError, refetch } = useProfitBreakdown(shopId, String(period));
  const products = useProducts(shopId, String(period), null, 'profit_desc', '');
  const toast = useToast();
  const [exporting, setExporting] = useState(false);

  if (isLoading) {
    return (
      <View style={{ flex: 1, padding: spacing.lg, gap: spacing.md, backgroundColor: colors.bg }}>
        <Skeleton height={28} width="60%" />
        {Array.from({ length: 6 }).map((_, i) => <Skeleton key={i} height={44} />)}
      </View>
    );
  }
  if (isError || !data) {
    return <ErrorState title={t('common.errorTitle')} body={t('common.errorBody')} onRetry={() => refetch()} />;
  }

  const base = Math.max(1, Math.abs(data.steps[0]?.minor ?? 1));
  const cov = products.data?.pages[0]?.coverage;

  return (
    <ScrollView contentContainerStyle={{ padding: spacing.lg, paddingBottom: 48, gap: spacing.md }} style={{ backgroundColor: colors.bg }}>
      <Card style={{ gap: spacing.md }}>
        <Txt variant="footnoteStrong" tone="secondary">{t('profit.coverageTitle', { done: cov?.complete ?? 0, total: cov?.total ?? 0 })}</Txt>
        <CoverageBar bp={data.coverage_bp} />
        <Txt variant="footnote" tone="tertiary">{formatPercentBp(data.coverage_bp)}</Txt>
      </Card>

      <Button
        title={t('profit.exportExcel')}
        variant="secondary"
        fullWidth
        loading={exporting}
        onPress={async () => {
          setExporting(true);
          try {
            await downloadAndShare(
              `/shops/${shopId}/exports/profit.xlsx?period=${encodeURIComponent(String(period))}`,
              `satti-pribyl-${data.period.from}_${data.period.to}.xlsx`,
              'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            );
          } catch {
            toast.show(t('common.unknownError'));
          } finally {
            setExporting(false);
          }
        }}
      />

      <Section title={t('overview.kpiProfit')}>
        <GroupCard>
          {data.steps.map((s, i) => {
            const isTotal = s.key === 'product_profit' || s.key === 'store_profit' || s.key === 'net_sales';
            const width = Math.min(100, (Math.abs(s.minor) / base) * 100);
            return (
              <View key={s.key} style={{ paddingVertical: spacing.md, paddingHorizontal: spacing.lg, gap: 6, borderTopWidth: i === 0 ? 0 : 1, borderTopColor: colors.divider }}>
                <View style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' }}>
                  <Txt variant={isTotal ? 'headline' : 'subhead'} tone={isTotal ? 'primary' : 'secondary'}>
                    {s.key === 'tax' && s.rate_bp != null
                      ? `${t('profit.steps.tax')} (${String(s.rate_bp / 100).replace('.', ',')}%)`
                      : t(`profit.steps.${s.key}` as never)}
                  </Txt>
                  <Txt variant={isTotal ? 'headline' : 'subhead'} numeric tone={s.minor < 0 ? 'danger' : isTotal ? 'primary' : 'secondary'}>
                    {formatMoney(s.minor, isTotal ? 'auto' : 'none')}
                  </Txt>
                </View>
                <View style={{ height: 6, borderRadius: radii.full, backgroundColor: colors.surfaceAlt, overflow: 'hidden' }}>
                  <View style={{ width: `${width}%`, height: 6, borderRadius: radii.full, backgroundColor: s.minor < 0 ? colors.danger : colors.primary }} />
                </View>
              </View>
            );
          })}
        </GroupCard>
      </Section>

      <Section title={t('profit.missingTitle')}>
        {data.missing.length === 0 ? (
          <EmptyState title={t('overview.allGood')} />
        ) : (
          <GroupCard>
            {data.missing.slice(0, 50).map((m, i, arr) => (
              <ListRow
                key={m.product_id}
                title={m.name}
                subtitle={m.sku}
                right={<Txt variant="footnote" tone="warning">{m.reason === 'no_cost' ? t('profit.missingNoCost') : t('profit.missingIncomplete')}</Txt>}
                onPress={() => router.push(`/product/${m.product_id}`)}
                last={i === arr.length - 1}
              />
            ))}
          </GroupCard>
        )}
      </Section>

      <Txt variant="footnote" tone="tertiary" style={{ marginTop: spacing.md }}>{data.note}</Txt>
      <Txt variant="footnote" tone="tertiary">{t('profit.howItWorks')}</Txt>
    </ScrollView>
  );
}
