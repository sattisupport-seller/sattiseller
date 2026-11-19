import { useRouter } from 'expo-router';
import { useMemo, useState } from 'react';
import { RefreshControl, ScrollView, View } from 'react-native';

import { useOrders } from '@/api/hooks';
import type { OrderRow } from '@/api/types';
import { Button } from '@/components/ui/Button';
import { TabHeader } from '@/components/ui/Header';
import { SearchField, Segmented } from '@/components/ui/Inputs';
import { Txt } from '@/components/ui/Text';
import { Badge, Chip, GroupCard, ListRow, Section, type Tone } from '@/components/ui/Surfaces';
import { EmptyState, ErrorState, Skeleton } from '@/components/ui/Overlays';
import { useSession } from '@/session/SessionProvider';
import { useI18n } from '@/i18n';
import { useTheme } from '@/theme/useTheme';
import {
  formatCount, formatDayLabel, formatMoney, formatOrderNumber, formatPeriodRange, formatTimeAlmaty, todayAlmaty,
} from '@/lib/format';

type Preset = '7d' | '30d' | '90d' | 'today';
const STATUS_TONE: Record<string, Tone> = {
  completed: 'success',
  in_progress: 'info',
  pending: 'neutral',
  returned: 'warning',
  partial_return: 'warning',
  cancelled: 'danger',
};
const STATUS_FILTER: { key: string | null; labelKey: 'chipAll' | 'chipCompleted' | 'chipOpen' | 'chipReturns' | 'chipCancelled' }[] = [
  { key: null, labelKey: 'chipAll' },
  { key: 'completed', labelKey: 'chipCompleted' },
  { key: 'open', labelKey: 'chipOpen' },
  { key: 'returns', labelKey: 'chipReturns' },
  { key: 'cancelled', labelKey: 'chipCancelled' },
];

// Список заказов по дням (docs/design.md, 12.6): поиск, фильтры по статусу и периоду, подгрузка по курсору.
export default function OrdersScreen() {
  const { t, locale } = useI18n();
  const { colors, spacing } = useTheme();
  const router = useRouter();
  const { shopId } = useSession();
  const [preset, setPreset] = useState<Preset>('7d');
  const [status, setStatus] = useState<string | null>(null);
  const [query, setQuery] = useState('');

  const orders = useOrders(shopId, preset, status, query.trim());
  const pages = orders.data?.pages ?? [];
  const rows: OrderRow[] = useMemo(() => pages.flatMap((p) => p.items), [pages]);
  const total = pages[0]?.total ?? 0;
  const today = todayAlmaty();
  const yesterday = new Date(Date.parse(`${today}T00:00:00Z`) - 86400_000).toISOString().slice(0, 10);

  const groups = useMemo(() => {
    const map = new Map<string, OrderRow[]>();
    for (const r of rows) {
      const day = r.created_at.slice(0, 10);
      map.set(day, [...(map.get(day) ?? []), r]);
    }
    return [...map.entries()];
  }, [rows]);

  const periodLabel = preset === '7d' ? t('overview.period7') : preset === '30d' ? t('overview.period30') : preset === '90d' ? t('overview.period90') : t('overview.periodToday');

  return (
    <View style={{ flex: 1, backgroundColor: colors.bg }}>
      <ScrollView
        contentContainerStyle={{ paddingHorizontal: spacing.lg, paddingBottom: 120, paddingTop: spacing.sm }}
        showsVerticalScrollIndicator={false}
        refreshControl={<RefreshControl refreshing={orders.isRefetching} onRefresh={() => { void orders.refetch(); }} tintColor={colors.primary} />}
      >
        <TabHeader
          title={t('orders.title')}
          subtitle={<Txt variant="subhead" tone="tertiary">{t('orders.subtitle', { period: periodLabel, count: formatCount(total, 'orders', locale) })}</Txt>}
        />

        <Segmented
          accessibilityLabel={t('orders.title')}
          value={preset}
          options={[
            { value: 'today' as Preset, label: t('overview.periodToday') },
            { value: '7d' as Preset, label: t('overview.period7') },
            { value: '30d' as Preset, label: t('overview.period30') },
            { value: '90d' as Preset, label: t('overview.period90') },
          ]}
          onChange={setPreset}
        />

        <View style={{ marginTop: spacing.md }}>
          <SearchField value={query} onChangeText={setQuery} placeholder={t('orders.searchPlaceholder')} />
        </View>

        <ScrollView horizontal showsHorizontalScrollIndicator={false} style={{ marginTop: spacing.md, marginBottom: spacing.xs }}>
          {STATUS_FILTER.map((f) => (
            <Chip key={f.labelKey} label={t(`orders.${f.labelKey}`)} selected={status === f.key} onPress={() => setStatus(f.key)} />
          ))}
        </ScrollView>

        {orders.isLoading ? (
          <View style={{ gap: spacing.md, marginTop: spacing.md }}>
            {Array.from({ length: 5 }).map((_, i) => <Skeleton key={i} height={64} radius={16} />)}
          </View>
        ) : null}

        {orders.isError && rows.length === 0 ? (
          <ErrorState title={t('common.errorTitle')} body={t('common.errorBody')} onRetry={() => orders.refetch()} />
        ) : null}

        {!orders.isLoading && !orders.isError && rows.length === 0 ? (
          <EmptyState
            title={t('orders.empty')}
            action={t('orders.reset')}
            onAction={() => {
              setStatus(null);
              setQuery('');
            }}
          />
        ) : null}

        {groups.map(([day, list]) => (
          <Section key={day} title={capitalize(formatDayLabel(day, today, locale, yesterday))}>
            <GroupCard>
              {list.map((o, i) => (
                <ListRow
                  key={o.id}
                  title={formatOrderNumber(o.number)}
                  subtitle={`${o.summary}`}
                  badges={<Badge label={t(`orders.status.${o.status}` as never)} tone={STATUS_TONE[o.status] ?? 'neutral'} />}
                  right={
                    <View style={{ alignItems: 'flex-end' }}>
                      <Txt variant="headline" numeric tone={o.status === 'cancelled' ? 'tertiary' : 'primary'}
                        style={o.status === 'cancelled' ? { textDecorationLine: 'line-through' } : undefined}>
                        {formatMoney(o.total_minor)}
                      </Txt>
                      <Txt variant="footnote" tone="tertiary">{formatTimeAlmaty(o.created_at)}</Txt>
                    </View>
                  }
                  onPress={() => router.push(`/order/${o.id}`)}
                  last={i === list.length - 1}
                />
              ))}
            </GroupCard>
          </Section>
        ))}

        {orders.hasNextPage ? (
          <View style={{ marginTop: spacing.lg }}>
            <Button title={t('common.more')} onPress={() => orders.fetchNextPage()} variant="secondary" fullWidth loading={orders.isFetchingNextPage} />
          </View>
        ) : null}

        <Txt variant="footnote" tone="tertiary" style={{ marginTop: spacing.xl }}>
          {formatPeriodRange(today, today, locale)}
        </Txt>
      </ScrollView>
    </View>
  );
}

function capitalize(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1);
}
