import { useRouter } from 'expo-router';
import { CalendarDays, CircleHelp, Sparkles } from 'lucide-react-native';
import { useMemo, useState, type ReactNode } from 'react';
import { Pressable, View } from 'react-native';

import { useOverview, useShops } from '@/api/hooks';
import { Button } from '@/components/ui/Button';
import { LineChart } from '@/components/ui/Charts';
import { IconButton } from '@/components/ui/IconButton';
import { Segmented, TextField } from '@/components/ui/Inputs';
import { TabHeader } from '@/components/ui/Header';
import { Txt } from '@/components/ui/Text';
import { Badge, Banner, Card, Chip, GroupCard, ListRow, Section } from '@/components/ui/Surfaces';
import { EmptyState, ErrorState, ScreenScroll, Sheet, Skeleton } from '@/components/ui/Overlays';
import { useSession } from '@/session/SessionProvider';
import { useI18n } from '@/i18n';
import { useTheme } from '@/theme/useTheme';
import {
  formatCount, formatDayLabel, formatMoney, formatMoneyShort, formatPercentBp, formatPeriodRange,
  formatTimeAlmaty, todayAlmaty,
} from '@/lib/format';

type Preset = '7d' | '30d' | '90d' | 'today';

// Обзор (docs/design.md, 12.4): период, KPI 2×2, график, «требует внимания», лучшие товары, помощник.
export default function OverviewScreen() {
  const { t, locale } = useI18n();
  const { colors, spacing, radii } = useTheme();
  const router = useRouter();
  const { shopId, isDemo } = useSession();

  const [preset, setPreset] = useState<Preset>('7d');
  const [custom, setCustom] = useState<string | null>(null);
  const [series, setSeries] = useState<'profit' | 'sales'>('profit');
  const [calendarOpen, setCalendarOpen] = useState(false);
  const [from, setFrom] = useState('');
  const [to, setTo] = useState('');
  const [rangeError, setRangeError] = useState<string | null>(null);

  const period = custom ?? preset;
  const query = useOverview(shopId, period);
  const { data, isLoading, isError, error, refetch, isRefetching } = query;
  const shopsQuery = useShops(!!shopId);
  const shopName = shopsQuery.data?.items.find((s) => s.id === shopId)?.name ?? null;

  const days = data?.series.days ?? [];
  const today = todayAlmaty();
  const labels = useMemo(() => days.map((d) => formatDayLabel(d, today, locale)), [days, today, locale]);
  const periodDays = String(days.length);
  const kpi = data?.kpi;
  const isEmpty = !!kpi && kpi.orders_count === 0 && kpi.net_sales_minor === 0;

  const applyCustom = () => {
    const iso = /^\d{4}-\d{2}-\d{2}$/;
    if (!iso.test(from) || !iso.test(to) || from > to) {
      setRangeError(t('common.errorBody'));
      return;
    }
    setRangeError(null);
    setCustom(`${from}..${to}`);
    setCalendarOpen(false);
  };

  const rangeLabel = data
    ? t('overview.compare', {
        range: formatPeriodRange(data.period.from, data.period.to, locale),
        prev: formatPeriodRange(data.comparison_period.from, data.comparison_period.to, locale),
      })
    : '';

  const chart = series === 'profit'
    ? { now: data?.series.profit ?? [], prev: data?.series.prev_profit ?? [] }
    : { now: data?.series.sales ?? [], prev: data?.series.prev_sales ?? [] };

  const attentionCount = data
    ? data.attention.in_minus.length + data.attention.many_returns.length + (data.attention.no_cost_count > 0 ? 1 : 0)
    : 0;

  return (
    <View style={{ flex: 1, backgroundColor: colors.bg }}>
      <ScreenScroll refreshing={isRefetching} onRefresh={() => refetch()}>
        <TabHeader
          title={t('overview.title')}
          subtitle={
            <>
              <Txt variant="subhead" tone="secondary">
                {shopName ? t('overview.store', { name: shopName }) : null}
              </Txt>
              {isDemo ? <Badge label={t('overview.demo')} tone="primary" /> : null}
            </>
          }
          right={
            <IconButton label={t('settings.howTitle')} onPress={() => router.push('/settings/how-profit')}>
              <CircleHelp size={24} color={colors.textSecondary} />
            </IconButton>
          }
        />

        {isDemo ? (
          <Banner text={t('overview.demoBanner')} tone="primary" action={t('overview.more')} onAction={() => router.push('/settings/how-profit')} />
        ) : null}

        <View style={{ flexDirection: 'row', alignItems: 'center', gap: spacing.sm, marginTop: spacing.md }}>
          <View style={{ flex: 1 }}>
            <Segmented
              accessibilityLabel={t('overview.onlyPeriod')}
              value={custom ? null : preset}
              options={[
                { value: 'today' as Preset, label: t('overview.periodToday') },
                { value: '7d' as Preset, label: t('overview.period7') },
                { value: '30d' as Preset, label: t('overview.period30') },
                { value: '90d' as Preset, label: t('overview.period90') },
              ]}
              onChange={(v) => {
                setPreset(v);
                setCustom(null);
              }}
            />
          </View>
          <IconButton label={t('overview.onlyPeriod')} onPress={() => setCalendarOpen(true)}>
            <CalendarDays size={22} color={colors.textSecondary} />
          </IconButton>
        </View>
        {rangeLabel ? <Txt variant="footnote" tone="tertiary" style={{ marginTop: spacing.sm }}>{rangeLabel}</Txt> : null}

        {isLoading ? <OverviewSkeleton /> : null}

        {isError && !data ? (
          <ErrorState title={t('common.errorTitle')} body={t('common.errorBody')} code={(error as { code?: string } | null)?.code} onRetry={() => refetch()} />
        ) : null}

        {isError && data ? (
          <Banner text={t('common.offline', { time: formatTimeAlmaty(data.data_as_of) })} tone="neutral" action={t('common.retry')} onAction={() => refetch()} />
        ) : null}

        {data && kpi ? (
          <>
            <View style={{ flexDirection: 'row', gap: spacing.md, marginTop: spacing.md }}>
              <KpiBox
                title={t('overview.kpiNet')}
                value={formatMoneyShort(kpi.net_sales_minor, 'kpi', locale)}
                delta={kpi.net_sales_delta_bp}
                deltaLabel={t('overview.vsPrev', { days: periodDays })}
              />
              <KpiBox
                title={t('overview.kpiProfit')}
                value={formatMoneyShort(kpi.profit_minor, 'kpi', locale)}
                delta={kpi.profit_delta_bp}
                deltaLabel={t('overview.vsPrev', { days: periodDays })}
                footer={
                  <Badge
                    label={t('overview.coverage', { pct: formatPercentBp(kpi.coverage_bp) })}
                    tone={kpi.coverage_bp >= 9500 ? 'success' : kpi.coverage_bp >= 7000 ? 'warning' : 'danger'}
                  />
                }
              />
            </View>
            <View style={{ flexDirection: 'row', gap: spacing.md, marginTop: spacing.md }}>
              <KpiBox
                title={t('overview.kpiOrders')}
                value={String(kpi.orders_count)}
                deltaCount={kpi.orders_delta}
                deltaLabel={t('overview.vsPrev', { days: periodDays })}
              />
              <KpiBox
                title={t('overview.kpiReturns')}
                value={String(kpi.returns_cancels_count)}
                deltaCount={kpi.returns_cancels_delta}
                deltaLabel={t('overview.vsPrev', { days: periodDays })}
                badWhenUp
              />
            </View>

            {isEmpty ? (
              <EmptyState title={t('overview.noOrders')} action={t('overview.pickPeriod')} onAction={() => setPreset('30d')} />
            ) : (
              <>
                <Card style={{ marginTop: spacing.md, gap: spacing.md }}>
                  <Txt variant="title3">{t('overview.profitByDay')}</Txt>
                  <View>
                    <Segmented
                      accessibilityLabel={t('overview.profitByDay')}
                      value={series}
                      options={[
                        { value: 'profit' as const, label: t('overview.segProfit') },
                        { value: 'sales' as const, label: t('overview.segSales') },
                      ]}
                      onChange={setSeries}
                    />
                  </View>
                  {days.length > 0 ? (
                    <LineChart
                      values={chart.now}
                      prev={chart.prev}
                      labels={labels}
                      format={(v) => formatMoney(v, 'auto')}
                      accessibilityLabel={`${t('overview.profitByDay')}: ${formatMoneyShort(kpi.profit_minor, 'list', locale)}`}
                    />
                  ) : null}
                  <View style={{ flexDirection: 'row', gap: spacing.md }}>
                    <Txt variant="caption" tone="primaryText">{t('overview.legendNow')}</Txt>
                    <Txt variant="caption" tone="tertiary">{t('overview.legendPrev')}</Txt>
                  </View>
                </Card>

                <Section title={t('overview.attention')}>
                  <GroupCard>
                    {data.attention.in_minus.map((p) => (
                      <ListRow
                        key={p.product_id}
                        title={t('overview.attentionMinus', { name: p.name })}
                        subtitle={p.sku}
                        badges={<Badge label={t('products.badgeInMinus')} tone="danger" />}
                        onPress={() => router.push(`/product/${p.product_id}`)}
                      />
                    ))}
                    {data.attention.no_cost_count > 0 ? (
                      <ListRow
                        title={t('overview.attentionNoCost', { count: data.attention.no_cost_count })}
                        subtitle={t('overview.attentionNoCostHint')}
                        right={<Txt variant="buttonS" tone="primaryText">{t('overview.fill')}</Txt>}
                        onPress={() => router.push('/quick-cost')}
                      />
                    ) : null}
                    {data.attention.many_returns.map((p) => (
                      <ListRow
                        key={p.product_id}
                        title={t('overview.attentionReturns', { name: p.name })}
                        subtitle={formatCount(p.returned_qty, 'units', locale)}
                        badges={<Badge label={t('products.badgeReturns')} tone="warning" />}
                        onPress={() => router.push(`/product/${p.product_id}`)}
                      />
                    ))}
                    {attentionCount === 0 ? <ListRow title={t('overview.allGood')} last /> : null}
                  </GroupCard>
                </Section>

                <Section title={t('overview.best')} action={t('overview.allProducts')} onAction={() => router.push('/(tabs)/products')}>
                  <GroupCard>
                    {data.best_products.map((p, i, arr) => (
                      <ListRow
                        key={p.product_id}
                        title={p.name}
                        subtitle={p.sku}
                        right={
                          <View style={{ alignItems: 'flex-end' }}>
                            <Txt variant="headline" tone={p.profit_minor !== null && p.profit_minor < 0 ? 'danger' : 'success'} numeric>
                              {p.profit_minor !== null ? formatMoney(p.profit_minor, 'auto') : t('common.na')}
                            </Txt>
                            {p.margin_bp !== null ? (
                              <Txt variant="footnote" tone="tertiary">{t('products.margin', { pct: formatPercentBp(p.margin_bp) })}</Txt>
                            ) : null}
                          </View>
                        }
                        onPress={() => router.push(`/product/${p.product_id}`)}
                        last={i === arr.length - 1}
                      />
                    ))}
                  </GroupCard>
                </Section>

                <View
                  style={{ marginTop: spacing['2xl'], backgroundColor: colors.surface, borderRadius: radii.lg, borderWidth: 1, borderColor: colors.border, padding: spacing.lg, gap: spacing.md }}
                >
                  <View style={{ flexDirection: 'row', alignItems: 'center', gap: spacing.md }}>
                    <View style={{ width: 40, height: 40, borderRadius: 20, backgroundColor: colors.primarySoft, alignItems: 'center', justifyContent: 'center' }}>
                      <Sparkles size={20} color={colors.onPrimarySoft} />
                    </View>
                    <View style={{ flex: 1 }}>
                      <Txt variant="headline">
                        {kpi.profit_delta_bp !== null && kpi.profit_delta_bp < 0
                          ? t('overview.assistantTitle', { change: formatPercentBp(kpi.profit_delta_bp), days: periodDays })
                          : t('overview.assistantAsk')}
                      </Txt>
                      <Txt variant="subhead" tone="secondary">{t('overview.assistantAsk')}</Txt>
                    </View>
                  </View>
                  <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm }}>
                    <Chip label={t('overview.assistantChip1')} selected={false} onPress={() => router.push('/(tabs)/assistant')} />
                    <Chip label={t('overview.assistantChip2')} selected={false} onPress={() => router.push('/(tabs)/assistant')} />
                  </View>
                </View>

                <Txt variant="footnote" tone="tertiary" align="center" style={{ marginTop: spacing.xl }}>
                  {t('overview.dataAt', { time: formatTimeAlmaty(data.data_as_of) })}
                </Txt>
              </>
            )}
          </>
        ) : null}
      </ScreenScroll>

      <Sheet visible={calendarOpen} onClose={() => setCalendarOpen(false)} title={t('overview.onlyPeriod')}>
        <TextField label={t('settings.periodFrom')} value={from} onChangeText={setFrom} placeholder="2026-11-01" keyboardType="numbers-and-punctuation" />
        <TextField label={t('settings.periodTo')} value={to} onChangeText={setTo} placeholder="2026-11-19" keyboardType="numbers-and-punctuation" error={rangeError} />
        <Button title={t('common.apply')} onPress={applyCustom} fullWidth />
      </Sheet>
    </View>
  );
}

function KpiBox({ title, value, delta, deltaCount, deltaLabel, footer, badWhenUp }: {
  title: string;
  value: string;
  delta?: number | null;
  deltaCount?: number;
  deltaLabel?: string;
  footer?: ReactNode;
  badWhenUp?: boolean;
}) {
  const { spacing } = useTheme();
  let deltaText: string | null = null;
  let tone: 'success' | 'danger' | 'tertiary' = 'tertiary';
  if (delta !== undefined && delta !== null) {
    deltaText = formatPercentBp(delta, 'auto');
    tone = delta >= 0 ? 'success' : 'danger';
  } else if (deltaCount !== undefined) {
    deltaText = `${deltaCount >= 0 ? '+' : '−'}${Math.abs(deltaCount)}`;
    const up = deltaCount > 0;
    if (deltaCount === 0) tone = 'tertiary';
    else tone = badWhenUp ? (up ? 'danger' : 'success') : up ? 'success' : 'danger';
  }
  return (
    <Card style={{ flex: 1, minHeight: 116, gap: 6, padding: spacing.md }} accessibilityLabel={`${title}: ${value}${deltaText ? `, ${deltaText}` : ''}`}>
      <Txt variant="footnoteStrong" tone="secondary">{title}</Txt>
      <Txt variant="kpi" numeric>{value}</Txt>
      {deltaText ? (
        <Txt variant="captionStrong" tone={tone}>
          {deltaText}
          <Txt variant="caption" tone="tertiary">{deltaLabel ? ` ${deltaLabel}` : ''}</Txt>
        </Txt>
      ) : null}
      {footer}
    </Card>
  );
}

function OverviewSkeleton() {
  const { spacing } = useTheme();
  return (
    <View style={{ gap: spacing.md, marginTop: spacing.md }}>
      <View style={{ flexDirection: 'row', gap: spacing.md }}>
        <Skeleton height={116} radius={16} />
        <Skeleton height={116} radius={16} />
      </View>
      <View style={{ flexDirection: 'row', gap: spacing.md }}>
        <Skeleton height={116} radius={16} />
        <Skeleton height={116} radius={16} />
      </View>
      <Skeleton height={200} radius={16} />
    </View>
  );
}
