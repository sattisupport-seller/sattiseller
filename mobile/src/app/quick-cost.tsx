import { useRouter } from 'expo-router';
import { useState } from 'react';
import { ScrollView, Switch, View } from 'react-native';

import { useBulkCost, useMissingCosts, type UnconfiguredProduct } from '@/api/hooks';
import { ApiError } from '@/api/client';
import { Button } from '@/components/ui/Button';
import { MoneyField, TextField } from '@/components/ui/Inputs';
import { EmptyState, ErrorState, Skeleton, useToast } from '@/components/ui/Overlays';
import { Txt } from '@/components/ui/Text';
import { Card } from '@/components/ui/Surfaces';
import { useSession } from '@/session/SessionProvider';
import { useI18n } from '@/i18n';
import { useTheme } from '@/theme/useTheme';
import { isMoneyInput } from '@/lib/format';

// Быстрый ввод с телефона (docs/spec.md, 3.4; К-24): товары без себестоимости или остатка — два обязательных поля.
// Остаток из прайса продавца (stockCount) подставляется, продавец подтверждает.
export default function QuickCostScreen() {
  const { t } = useI18n();
  const { colors, spacing } = useTheme();
  const router = useRouter();
  const toast = useToast();
  const { shopId } = useSession();
  const missing = useMissingCosts(shopId);
  const save = useBulkCost(shopId);
  const [prices, setPrices] = useState<Record<string, string>>({});
  const [stocks, setStocks] = useState<Record<string, string>>({});
  const [applyAll, setApplyAll] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const items = missing.data?.items ?? [];
  const needsCost = (i: UnconfiguredProduct) => i.needs_cost !== false;
  const needsStock = (i: UnconfiguredProduct) => i.needs_stock !== false;
  const stockOf = (i: UnconfiguredProduct) =>
    stocks[i.product_id] ?? (i.stock_hint !== null && i.stock_hint !== undefined ? String(i.stock_hint) : '');
  // товар готов к сохранению, когда заполнены все его обязательные поля
  const filled = items.filter((i) =>
    (!needsCost(i) || (prices[i.product_id] ?? '').trim() !== '') && (!needsStock(i) || stockOf(i).trim() !== ''));

  const submit = async () => {
    const bad = filled.find((i) => needsCost(i) && !isMoneyInput(prices[i.product_id]));
    if (bad) {
      setError(t('cost.invalid'));
      return;
    }
    if (filled.length === 0) return;
    try {
      await save.mutateAsync({
        items: filled.map((i) => ({
          product_id: i.product_id,
          ...(needsCost(i) ? { purchase: prices[i.product_id].replace(/\s/g, '').replace(',', '.') } : {}),
          ...(needsStock(i) ? { stock_qty: Number(stockOf(i)) } : {}),
        })),
        apply_to_history: applyAll,
      });
      toast.show(t('quickCost.saved'));
      router.back();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : t('common.unknownError'));
    }
  };

  if (missing.isLoading) {
    return <View style={{ flex: 1, padding: spacing.lg, gap: spacing.md, backgroundColor: colors.bg }}><Skeleton height={60} radius={16} /></View>;
  }
  if (missing.isError) {
    return <ErrorState title={t('common.errorTitle')} body={t('common.errorBody')} onRetry={() => missing.refetch()} />;
  }
  if (items.length === 0) {
    return <EmptyState title={t('quickCost.empty')} />;
  }

  return (
    <ScrollView contentContainerStyle={{ padding: spacing.lg, paddingBottom: 140, gap: spacing.md }} style={{ backgroundColor: colors.bg }} keyboardShouldPersistTaps="handled">
      <Txt variant="title3">{t('quickCost.subtitle', { count: items.length })}</Txt>
      <Txt variant="footnote" tone="secondary">{t('quickCost.filled', { done: filled.length, total: items.length })}</Txt>

      {items.map((i) => (
        <Card key={i.product_id} style={{ gap: spacing.sm }}>
          <Txt variant="bodyMedium">{i.name}</Txt>
          <Txt variant="footnote" tone="tertiary">{i.sku}</Txt>
          {needsCost(i) ? (
            <MoneyField
              label={t('cost.purchase')}
              value={prices[i.product_id] ?? ''}
              onChangeText={(v) => {
                setPrices((p) => ({ ...p, [i.product_id]: v }));
                setError(null);
              }}
              placeholder="0"
              accessibilityLabel={`${i.name}: ${t('cost.purchase')}`}
            />
          ) : null}
          {needsStock(i) ? (
            <TextField
              label={t('cost.stock')}
              value={stockOf(i)}
              onChangeText={(v) => {
                setStocks((p) => ({ ...p, [i.product_id]: v.replace(/\D/g, '').slice(0, 7) }));
                setError(null);
              }}
              keyboardType="number-pad"
              placeholder="0"
              accessibilityLabel={`${i.name}: ${t('cost.stock')}`}
              hint={stocks[i.product_id] === undefined && i.stock_hint !== null && i.stock_hint !== undefined
                ? t('cost.stockFromPrice') : undefined}
            />
          ) : null}
        </Card>
      ))}

      <Card style={{ flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: spacing.md }}>
        <View style={{ flex: 1 }}>
          <Txt variant="bodyMedium">{t('quickCost.applyAll')}</Txt>
          <Txt variant="footnote" tone="tertiary">{t('quickCost.applyAllHint')}</Txt>
        </View>
        <Switch value={applyAll} onValueChange={setApplyAll} accessibilityLabel={t('quickCost.applyAll')} trackColor={{ true: colors.primary }} />
      </Card>

      {error ? <Txt variant="footnote" tone="danger">{error}</Txt> : null}

      <View style={{ position: 'absolute', left: 0, right: 0, bottom: 0, padding: spacing.lg, backgroundColor: colors.surface, borderTopWidth: 1, borderTopColor: colors.divider }}>
        <Button
          title={t('quickCost.saveN', { count: filled.length })}
          onPress={submit}
          loading={save.isPending}
          disabled={filled.length === 0}
          fullWidth
        />
      </View>
    </ScrollView>
  );
}
