import { useLocalSearchParams, useRouter } from 'expo-router';
import { Sparkles } from 'lucide-react-native';
import { useState } from 'react';
import { ScrollView, View } from 'react-native';

import { useProduct } from '@/api/hooks';
import { Button } from '@/components/ui/Button';
import { BarChart } from '@/components/ui/Charts';
import { Segmented } from '@/components/ui/Inputs';
import { Txt } from '@/components/ui/Text';
import { Badge, Banner, Card, GroupCard, ListRow, Section, type Tone } from '@/components/ui/Surfaces';
import { ErrorState, Skeleton } from '@/components/ui/Overlays';
import { useSession } from '@/session/SessionProvider';
import { useI18n } from '@/i18n';
import { useTheme } from '@/theme/useTheme';
import { formatDayLabel, formatMoney, formatMoneyShort, formatPercentBp, formatPeriodRange, todayAlmaty, formatCount } from '@/lib/format';

type Period = '7d' | '30d' | '90d';

// Карточка товара (docs/design.md, 12.9): KPI, график продаж, экономика одной продажи, затраты, возвраты.
export default function ProductScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const { t, locale } = useI18n();
  const { colors, spacing } = useTheme();
  const router = useRouter();
  const { shopId } = useSession();
  const [period, setPeriod] = useState<Period>('30d');
  const { data, isLoading, isError, refetch } = useProduct(shopId, String(id), period);
  const today = todayAlmaty();

  if (isLoading) {
    return (
      <View style={{ flex: 1, padding: spacing.lg, gap: spacing.md, backgroundColor: colors.bg }}>
        <Skeleton height={28} width="70%" />
        <Skeleton height={100} radius={16} />
        <Skeleton height={160} radius={16} />
      </View>
    );
  }
  if (isError || !data) {
    return <ErrorState title={t('common.errorTitle')} body={t('common.errorBody')} onRetry={() => refetch()} />;
  }

  const p = data.product;
  const sold = p.sold_qty;
  const returnsCount = data.returns.reduce((s, r) => s + r.qty, 0);
  const hasCost = !!data.current_cost;
  const dailyLabels = data.daily_units.map((d) => formatDayLabel(d.day, today, locale));

  return (
    <ScrollView contentContainerStyle={{ padding: spacing.lg, paddingBottom: 48, gap: spacing.md }} style={{ backgroundColor: colors.bg }}>
      <View style={{ gap: spacing.sm }}>
        <Txt variant="title2" accessibilityRole="header">{p.name}</Txt>
        <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
          <Txt variant="subhead" tone="tertiary">{t('productDetail.sku', { sku: p.sku, category: p.category })}</Txt>
          <Badge label={data.data_complete ? t('productDetail.complete') : t('productDetail.incomplete')} tone={data.data_complete ? 'success' : 'warning'} />
        </View>
      </View>

      <Segmented
        accessibilityLabel={t('overview.onlyPeriod')}
        value={period}
        options={[
          { value: '7d' as Period, label: t('overview.period7') },
          { value: '30d' as Period, label: t('overview.period30') },
          { value: '90d' as Period, label: t('overview.period90') },
        ]}
        onChange={setPeriod}
      />

      <View style={{ flexDirection: 'row', gap: spacing.sm }}>
        <MiniKpi title={t('productDetail.sold')} value={formatCount(sold, 'units', locale)} />
        <MiniKpi title={t('productDetail.profit')} value={p.profit_minor === null ? '—' : formatMoneyShort(p.profit_minor, 'kpi', locale)} tone={p.profit_minor !== null && p.profit_minor < 0 ? 'danger' : 'primary'} />
        <MiniKpi title={t('productDetail.margin')} value={p.margin_bp === null ? '—' : formatPercentBp(p.margin_bp)} />
      </View>

      <Card style={{ gap: spacing.sm }}>
        <Txt variant="title3">{t('productDetail.daily')}</Txt>
        <BarChart
          values={data.daily_units.map((d) => d.qty)}
          labels={dailyLabels}
          accessibilityLabel={`${t('productDetail.daily')}: ${formatCount(sold, 'units', locale)}`}
        />
        <Txt variant="footnote" tone="tertiary">{formatPeriodRange(data.period.from, data.period.to, locale)}</Txt>
      </Card>

      {!hasCost ? (
        <Banner text={t('productDetail.noEconomy')} tone="warning" action={t('productDetail.addCost')} onAction={() => router.push(`/product/cost/${p.product_id}`)} />
      ) : null}

      {data.economics ? (
        <Section title={t('productDetail.economy')}>
          <Card style={{ gap: spacing.sm }}>
            <Line label={t('productDetail.avgPrice')} value={formatMoney(data.economics.avg_price_minor)} />
            <Line label={t('productDetail.landed')} value={formatMoney(-data.economics.landed_minor)} />
            <Line label={t('productDetail.commission', { pct: formatPercentBp(data.economics.commission_bp) })} value={formatMoney(-data.economics.commission_minor)} />
            <Line label={t('productDetail.delivery')} value={formatMoney(-data.economics.delivery_minor)} />
            {data.economics.tax_minor != null ? (
              <Line label={t('profit.steps.tax')} value={formatMoney(-data.economics.tax_minor)} />
            ) : null}
            <View style={{ height: 1, backgroundColor: colors.divider }} />
            <Line label={t('productDetail.profitPerSale')} value={formatMoney(data.economics.profit_per_unit_minor, 'auto')} strong />
          </Card>
        </Section>
      ) : null}

      <Section title={t('productDetail.costTitle')} action={t('productDetail.changeCost')} onAction={() => router.push(`/product/cost/${p.product_id}`)}>
        <Card style={{ gap: spacing.sm }}>
          {data.current_cost ? (
            <>
              <Line label={t('cost.purchase')} value={formatMoney(data.current_cost.purchase_minor)} />
              <Line label={t('cost.deliveryWh')} value={formatMoney(data.current_cost.delivery_to_warehouse_minor)} />
              <Line label={t('cost.packaging')} value={formatMoney(data.current_cost.packaging_minor)} />
              <Line label={t('cost.other')} value={formatMoney(data.current_cost.other_minor)} />
              <Txt variant="footnote" tone="tertiary">
                {t('productDetail.costSource', { src: data.current_cost.source })}
                {data.current_cost.effective_from ? ` · ${formatDayLabel(data.current_cost.effective_from, today, locale)}` : ''}
              </Txt>
            </>
          ) : (
            <Txt variant="subhead" tone="secondary">{t('productDetail.noEconomy')}</Txt>
          )}
          {data.cost_history.length > 1 ? (
            <Txt variant="buttonS" tone="primaryText" onPress={() => router.push(`/product/cost/${p.product_id}`)}>
              {t('productDetail.history', { count: data.cost_history.length })}
            </Txt>
          ) : null}
        </Card>
      </Section>

      <Section title={t('productDetail.returns')}>
        <Card>
          <Txt variant="bodyMedium">
            {returnsCount > 0 ? t('productDetail.returnsLine', { count: returnsCount, sold }) : t('productDetail.noReturns')}
          </Txt>
        </Card>
      </Section>

      <Button
        title={t('productDetail.askAssistant')}
        onPress={() => router.push('/(tabs)/assistant')}
        icon={<Sparkles size={20} color={colors.onPrimary} />}
        fullWidth
        style={{ marginTop: spacing.lg }}
      />
      {hasCost ? null : <GroupCard><ListRow title={t('productDetail.addCost')} onPress={() => router.push(`/product/cost/${p.product_id}`)} last /></GroupCard>}
    </ScrollView>
  );
}

function MiniKpi({ title, value, tone = 'primary' }: { title: string; value: string; tone?: Tone | 'primary' }) {
  const { colors, spacing, radii } = useTheme();
  return (
    <View style={{ flex: 1, backgroundColor: colors.surface, borderRadius: radii.md, borderWidth: 1, borderColor: colors.border, padding: spacing.sm, minHeight: 88, gap: 4 }}>
      <Txt variant="caption" tone="secondary">{title}</Txt>
      <Txt variant="headline" numeric tone={tone === 'danger' ? 'danger' : 'primary'}>{value}</Txt>
    </View>
  );
}

function Line({ label, value, strong }: { label: string; value: string; strong?: boolean }) {
  return (
    <View style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' }}>
      <Txt variant={strong ? 'headline' : 'subhead'} tone={strong ? 'primary' : 'secondary'}>{label}</Txt>
      <Txt variant={strong ? 'headline' : 'bodyMedium'} numeric>{value}</Txt>
    </View>
  );
}
