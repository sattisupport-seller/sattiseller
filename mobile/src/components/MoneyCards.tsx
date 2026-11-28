import { useRouter } from 'expo-router';
import { View } from 'react-native';

import { useMoneyInsights } from '@/api/hooks';
import { Button } from '@/components/ui/Button';
import { Card, GroupCard, ListRow } from '@/components/ui/Surfaces';
import { Txt } from '@/components/ui/Text';
import { useI18n } from '@/i18n';
import { formatCount, formatMoney, formatPercentBp } from '@/lib/format';
import { useTheme } from '@/theme/useTheme';

// К-33 А5: главный экран языком денег — утечки маржи, минимальная цена без убытка, порог доставки,
// защита от отмен, экономия времени. Все числа считает сервер (GET /shops/{id}/money).
export function MoneyCards({ shopId }: { shopId: string | null }) {
  const { t } = useI18n();
  const { spacing } = useTheme();
  const router = useRouter();
  const money = useMoneyInsights(shopId);
  const d = money.data;
  if (!d) return null;
  const leaks = d.leaks;
  const cp = d.cancel_protection;
  const overLimit = cp.cancel_share_bp >= cp.kaspi_limit_bp;

  return (
    <View style={{ gap: spacing.md, marginTop: spacing.md }}>
      <Card style={{ gap: spacing.sm }}>
        <Txt variant="headline">{t('money.leaksTitle')}</Txt>
        {leaks.losing_count > 0 ? (
          <Txt variant="title3" tone="danger">
            {t('money.leaksLoss', { sum: formatMoney(leaks.month_loss_minor), products: formatCount(leaks.losing_count, 'products') })}
          </Txt>
        ) : (
          <Txt variant="body" tone="secondary">{t('money.leaksNone')}</Txt>
        )}
        {leaks.items.length > 0 ? (
          <GroupCard>
            {leaks.items.slice(0, 5).map((i, idx) => (
              <ListRow
                key={i.product_id}
                title={i.name}
                subtitle={t('money.leakRow', {
                  profit: formatMoney(i.profit_minor, 'auto'),
                  commission: formatMoney(i.per_unit.commission),
                  delivery: formatMoney(i.per_unit.delivery),
                  min: formatMoney(i.min_price_minor),
                  price: formatMoney(i.avg_price_minor),
                })}
                onPress={() => router.push(`/product/${i.product_id}`)}
                last={idx === Math.min(leaks.items.length, 5) - 1}
              />
            ))}
          </GroupCard>
        ) : null}
        <Txt variant="footnote" tone="tertiary">{t('money.leaksNote')}</Txt>
      </Card>

      {d.threshold_hints.length > 0 ? (
        <Card style={{ gap: spacing.sm }}>
          <Txt variant="headline">{t('money.thresholdTitle')}</Txt>
          {d.threshold_hints.slice(0, 3).map((h) => (
            <Txt key={h.product_id} variant="body">
              {t('money.thresholdRow', { name: h.name, price: formatMoney(h.price_minor),
                suggested: formatMoney(h.suggested_price_minor), gain: formatMoney(h.gain_per_order_minor) })}
            </Txt>
          ))}
        </Card>
      ) : null}

      <Card style={{ gap: spacing.sm }}>
        <Txt variant="headline">{t('money.cancelTitle')}</Txt>
        <Txt variant="body" tone={overLimit ? 'danger' : undefined}>
          {t('money.cancelShare', { share: formatPercentBp(cp.cancel_share_bp), limit: formatPercentBp(cp.kaspi_limit_bp),
            cancelled: cp.cancelled_count, orders: formatCount(cp.orders_count, 'orders') })}
        </Txt>
        <Txt variant="body">
          {t(cp.preview ? 'money.protectedPreview' : 'money.protected', { products: formatCount(cp.protected_count, 'products') })}
        </Txt>
        <Txt variant="footnote" tone="tertiary">{cp.note}</Txt>
        <Button title={t('money.toStock')} variant="secondary" onPress={() => router.push('/stock')} fullWidth />
      </Card>

      <Card style={{ gap: spacing.sm }}>
        <Txt variant="headline">{t('money.timeTitle')}</Txt>
        <Txt variant="footnote" tone="secondary">{t('money.timeBody')}</Txt>
        <View style={{ flexDirection: 'row', gap: spacing.sm, flexWrap: 'wrap' }}>
          <Button title={t('money.aiCard')} variant="secondary" size="S" onPress={() => router.push('/assistant/product-draft')} />
          <Button title={t('money.replies')} variant="secondary" size="S" onPress={() => router.push('/assistant/reply-draft')} />
        </View>
      </Card>
    </View>
  );
}
