import { useRouter } from 'expo-router';
import { FileSpreadsheet, FileUp } from 'lucide-react-native';
import { useMemo, useState } from 'react';
import { RefreshControl, ScrollView, View } from 'react-native';

import { useProducts } from '@/api/hooks';
import type { ProductRow } from '@/api/types';
import { Button } from '@/components/ui/Button';
import { TabHeader } from '@/components/ui/Header';
import { IconButton } from '@/components/ui/IconButton';
import { SearchField, Segmented } from '@/components/ui/Inputs';
import { Txt } from '@/components/ui/Text';
import { Badge, Card, Chip, CoverageBar, GroupCard, ListRow, type Tone } from '@/components/ui/Surfaces';
import { EmptyState, ErrorState, Skeleton, useToast } from '@/components/ui/Overlays';
import { useSession } from '@/session/SessionProvider';
import { downloadAndShare } from '@/lib/download';
import { useI18n } from '@/i18n';
import { useTheme } from '@/theme/useTheme';
import { formatCount, formatMoney, formatPercentBp } from '@/lib/format';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

type Preset = '7d' | '30d' | '90d';
type Sort = 'profit_desc' | 'profit_asc' | 'sales' | 'margin' | 'name';

const FILTERS: { key: string | null; label: 'chipAll' | 'chipInMinus' | 'chipNoCost' | 'chipReturns' | 'chipNoSales' }[] = [
  { key: null, label: 'chipAll' },
  { key: 'in_minus', label: 'chipInMinus' },
  { key: 'no_cost', label: 'chipNoCost' },
  { key: 'many_returns', label: 'chipReturns' },
  { key: 'no_sales', label: 'chipNoSales' },
];

const SORTS: Sort[] = ['profit_desc', 'profit_asc', 'sales', 'margin', 'name'];

// Список товаров (docs/design.md, 12.8): покрытие, фильтры, сортировка, поиск.
export default function ProductsScreen() {
  const insets = useSafeAreaInsets();  // К-35 п.5: шапка не под строкой состояния и «островком»
  const { t, locale } = useI18n();
  const { colors, spacing } = useTheme();
  const toast = useToast();
  const router = useRouter();
  const { shopId } = useSession();
  const [preset, setPreset] = useState<Preset>('30d');
  const [filter, setFilter] = useState<string | null>(null);
  const [sort, setSort] = useState<Sort>('profit_asc');  // К-18: убыточные товары сверху
  const [query, setQuery] = useState('');

  const products = useProducts(shopId, preset, filter, sort, query.trim());
  const pages = products.data?.pages ?? [];
  const rows: ProductRow[] = useMemo(() => pages.flatMap((p) => p.items), [pages]);
  const coverage = pages[0]?.coverage;
  const total = pages[0]?.total ?? 0;
  const coverageBp = coverage && coverage.total > 0 ? Math.round((coverage.complete * 10000) / coverage.total) : 10000;
  // К-18: сколько продаваемых товаров без себестоимости — подсказка, а не нули в прибыли
  const noCostCount = (pages[0] as { no_cost_count?: number } | undefined)?.no_cost_count ?? (coverage ? coverage.total - coverage.complete : 0);

  return (
    <View style={{ flex: 1, backgroundColor: colors.bg, paddingTop: insets.top }}>
      <ScrollView
        contentContainerStyle={{ paddingHorizontal: spacing.lg, paddingBottom: 120, paddingTop: spacing.sm }}
        showsVerticalScrollIndicator={false}
        refreshControl={<RefreshControl refreshing={products.isRefetching} onRefresh={() => { void products.refetch(); }} tintColor={colors.primary} />}
      >
        <TabHeader
          title={t('products.title')}
          subtitle={<Txt variant="subhead" tone="tertiary">{formatCount(total, 'products', locale)}</Txt>}
          right={
            <View style={{ flexDirection: 'row', gap: spacing.sm }}>
              <IconButton
                label={t('products.exportExcel')}
                onPress={() => {
                  downloadAndShare(
                    `/shops/${shopId}/exports/profit.xlsx?period=${preset}`,
                    `satti-tovary-${preset}.xlsx`,
                    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                  ).catch(() => toast.show(t('common.unknownError')));
                }}
              >
                <FileSpreadsheet size={22} color={colors.textSecondary} />
              </IconButton>
              <IconButton label={t('products.upload')} onPress={() => router.push('/import')}>
                <FileUp size={22} color={colors.textSecondary} />
              </IconButton>
            </View>
          }
        />

        <SearchField value={query} onChangeText={setQuery} placeholder={t('products.searchPlaceholder')} />

        {coverage && noCostCount > 0 ? (
          <Card style={{ marginTop: spacing.md, gap: spacing.sm }}>
            <View style={{ flexDirection: 'row', justifyContent: 'space-between' }}>
              <Txt variant="headline">{t('products.coverageTitle', { done: coverage.complete, total: coverage.total })}</Txt>
              <Txt variant="headline" tone={coverageBp >= 9500 ? 'success' : 'warning'}>{formatPercentBp(coverageBp)}</Txt>
            </View>
            <CoverageBar bp={coverageBp} />
            <Txt variant="footnote" tone="secondary">{t('products.coverageNote', { count: noCostCount })}</Txt>
            <View style={{ flexDirection: 'row', gap: spacing.sm, marginTop: spacing.xs }}>
              <Button title={t('products.fill')} size="S" onPress={() => router.push('/quick-cost')} />
              <Button title={t('products.upload')} size="S" variant="outline" icon={<FileUp size={16} color={colors.textPrimary} />} onPress={() => router.push('/import')} />
            </View>
          </Card>
        ) : null}

        <View style={{ marginTop: spacing.md }}>
          <Segmented
            accessibilityLabel={t('products.sortBy', { period: '' })}
            value={preset}
            options={[
              { value: '7d' as Preset, label: t('overview.period7') },
              { value: '30d' as Preset, label: t('overview.period30') },
              { value: '90d' as Preset, label: t('overview.period90') },
            ]}
            onChange={setPreset}
          />
        </View>

        <ScrollView horizontal showsHorizontalScrollIndicator={false} style={{ marginTop: spacing.md }}>
          {FILTERS.map((f) => (
            <Chip key={f.label} label={t(`products.${f.label}`)} selected={filter === f.key} onPress={() => setFilter(f.key)} />
          ))}
        </ScrollView>

        <View style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginTop: spacing.lg, marginBottom: spacing.sm }}>
          <Txt variant="footnoteStrong" tone="secondary">{t('products.sortBy', { period: t(`overview.period${preset.replace('d', '')}` as never) })}</Txt>
          <Txt variant="buttonS" tone="primaryText" onPress={() => setSort(SORTS[(SORTS.indexOf(sort) + 1) % SORTS.length])}>
            {t(`products.sort.${sort}`)}
          </Txt>
        </View>

        {products.isLoading ? (
          <View style={{ gap: spacing.md }}>
            {Array.from({ length: 5 }).map((_, i) => <Skeleton key={i} height={64} radius={16} />)}
          </View>
        ) : null}
        {products.isError && rows.length === 0 ? (
          <ErrorState title={t('common.errorTitle')} body={t('common.errorBody')} onRetry={() => products.refetch()} />
        ) : null}
        {!products.isLoading && !products.isError && rows.length === 0 ? <EmptyState title={t('products.empty')} /> : null}

        {rows.length > 0 ? (
          <GroupCard>
            {rows.map((p, i) => (
              <ListRow
                key={p.product_id}
                title={p.name}
                subtitle={`${p.sku} · ${formatCount(p.sold_qty, 'units', locale)}`}
                badges={p.badges.length ? <BadgeRow badges={p.badges} /> : undefined}
                right={
                  <View style={{ alignItems: 'flex-end' }}>
                    {p.profit_minor === null ? (
                      <Txt variant="headline" tone="tertiary">—</Txt>
                    ) : (
                      <Txt variant="headline" numeric tone={p.profit_minor < 0 ? 'danger' : 'success'}>
                        {formatMoney(p.profit_minor, 'auto')}
                      </Txt>
                    )}
                    <Txt variant="footnote" tone="tertiary">
                      {p.margin_bp !== null ? t('products.margin', { pct: formatPercentBp(p.margin_bp) }) : t('products.noData')}
                    </Txt>
                  </View>
                }
                onPress={() => router.push(`/product/${p.product_id}`)}
                last={i === rows.length - 1}
              />
            ))}
          </GroupCard>
        ) : null}

        {products.hasNextPage ? (
          <View style={{ marginTop: spacing.lg }}>
            <Button title={t('common.more')} onPress={() => products.fetchNextPage()} variant="secondary" fullWidth loading={products.isFetchingNextPage} />
          </View>
        ) : null}
      </ScrollView>
    </View>
  );
}

function BadgeRow({ badges }: { badges: ProductRow['badges'] }) {
  const { t } = useI18n();
  const map: Record<string, { label: string; tone: Tone }> = {
    in_minus: { label: t('products.badgeInMinus'), tone: 'danger' },
    no_cost: { label: t('products.badgeNoCost'), tone: 'warning' },
    many_returns: { label: t('products.badgeReturns'), tone: 'warning' },
    no_sales: { label: t('products.badgeNoSales'), tone: 'neutral' },
  };
  return (
    <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 6 }}>
      {badges.map((b) => (
        <Badge key={b} label={map[b].label} tone={map[b].tone} />
      ))}
    </View>
  );
}
