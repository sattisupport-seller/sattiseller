import { useLocalSearchParams, useRouter } from 'expo-router';
import { ScrollView, View } from 'react-native';

import { useOrder } from '@/api/hooks';
import { Badge, Card, GroupCard, ListRow, Section, type Tone } from '@/components/ui/Surfaces';
import { ErrorState, Skeleton } from '@/components/ui/Overlays';
import { Txt } from '@/components/ui/Text';
import { useSession } from '@/session/SessionProvider';
import { useI18n } from '@/i18n';
import { useTheme } from '@/theme/useTheme';
import { formatDateTime, formatMoney, formatOrderNumber, todayAlmaty } from '@/lib/format';

const STATUS_TONE: Record<string, Tone> = {
  completed: 'success', in_progress: 'info', pending: 'neutral', returned: 'warning', partial_return: 'warning', cancelled: 'danger',
};

// Карточка заказа (docs/design.md, 12.7): товары, деньги по заказу с источниками, возвраты. Данных покупателя нет.
export default function OrderScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const { t, locale } = useI18n();
  const { colors, spacing } = useTheme();
  const router = useRouter();
  const { shopId } = useSession();
  const { data, isLoading, isError, refetch } = useOrder(shopId, String(id));
  const today = todayAlmaty();

  if (isLoading) {
    return (
      <View style={{ flex: 1, padding: spacing.lg, gap: spacing.md, backgroundColor: colors.bg }}>
        <Skeleton height={28} width="50%" />
        <Skeleton height={120} radius={16} />
      </View>
    );
  }
  if (isError || !data) {
    return <ErrorState title={t('common.errorTitle')} body={t('common.errorBody')} onRetry={() => refetch()} />;
  }

  const gross = data.items.reduce((s, i) => s + i.gross_minor, 0);
  const commission = data.items.reduce((s, i) => s + (i.commission_minor ?? 0), 0);
  const landed = data.items.reduce((s, i) => s + (i.landed_minor ?? 0), 0);
  const profitKnown = data.items.every((i) => i.profit_minor !== null);
  const profit = data.items.reduce((s, i) => s + (i.profit_minor ?? 0), 0);

  return (
    <ScrollView contentContainerStyle={{ padding: spacing.lg, paddingBottom: 48, gap: spacing.md }} style={{ backgroundColor: colors.bg }}>
      <View style={{ gap: spacing.sm }}>
        <Txt variant="title2" accessibilityRole="header">{formatOrderNumber(data.number)}</Txt>
        <Badge label={t(`orders.status.${data.status}` as never)} tone={STATUS_TONE[data.status] ?? 'neutral'} />
        <Txt variant="subhead" tone="secondary">{t('orderDetail.created', { when: formatDateTime(data.created_at, today, locale) })}</Txt>
        {data.completed_at ? (
          <Txt variant="subhead" tone="secondary">{t('orderDetail.completed', { when: formatDateTime(data.completed_at, today, locale) })}</Txt>
        ) : null}
      </View>

      <Section title={t('orderDetail.items')}>
        <GroupCard>
          {data.items.map((i, idx) => (
            <ListRow
              key={`${i.product_id}-${idx}`}
              title={i.name}
              subtitle={`${i.sku} · ${i.qty} × ${formatMoney(i.unit_price_minor)} = ${formatMoney(i.gross_minor)}`}
              onPress={() => router.push(`/product/${i.product_id}`)}
              last={idx === data.items.length - 1}
            />
          ))}
        </GroupCard>
      </Section>

      <Section title={t('orderDetail.money')}>
        <Card style={{ gap: spacing.sm }}>
          <Row label={t('orderDetail.gross')} value={formatMoney(gross)} />
          <Row label={t('orderDetail.landed')} value={formatMoney(landed, 'none')} />
          <Row label={t('orderDetail.commission')} value={formatMoney(commission)} />
          <Row label={t('orderDetail.profit')} value={profitKnown ? formatMoney(profit, 'auto') : '—'} strong tone={profitKnown && profit < 0 ? 'danger' : 'primary'} />
          <Txt variant="footnote" tone="tertiary">
            {data.items.map((i) => `${i.sku}: ${i.cost_source}; ${t('orderDetail.source', { src: i.commission_source })}`).join('\n')}
          </Txt>
        </Card>
      </Section>

      {data.items.some((i) => i.returns.length > 0) ? (
        <Section title={t('orderDetail.returns')}>
          <GroupCard>
            {data.items.flatMap((i) => i.returns.map((r, idx) => (
              <ListRow
                key={`${i.product_id}-${r.day}-${idx}`}
                title={`${r.day} · ${r.qty} ${locale === 'kk' ? 'дана' : 'шт.'}`}
                subtitle={i.name}
                right={<Txt variant="headline" numeric>{formatMoney(r.refund_minor)}</Txt>}
              />
            )))}
          </GroupCard>
        </Section>
      ) : null}

      <Txt variant="footnote" tone="tertiary" style={{ marginTop: spacing.md }}>{t('orderDetail.noBuyer')}</Txt>
    </ScrollView>
  );
}

function Row({ label, value, strong, tone = 'primary' }: { label: string; value: string; strong?: boolean; tone?: 'primary' | 'danger' }) {
  return (
    <View style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' }}>
      <Txt variant={strong ? 'headline' : 'subhead'} tone={tone === 'danger' ? 'danger' : strong ? 'primary' : 'secondary'}>{label}</Txt>
      <Txt variant={strong ? 'headline' : 'bodyMedium'} numeric tone={tone === 'danger' ? 'danger' : 'primary'}>{value}</Txt>
    </View>
  );
}
