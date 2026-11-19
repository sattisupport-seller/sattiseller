import { useState } from 'react';
import { ScrollView, View } from 'react-native';

import { useDeleteExpense, useExpenses, useSaveExpense } from '@/api/hooks';
import { ApiError } from '@/api/client';
import { Button } from '@/components/ui/Button';
import { MoneyField, Segmented, TextField } from '@/components/ui/Inputs';
import { Txt } from '@/components/ui/Text';
import { Card, GroupCard, ListRow } from '@/components/ui/Surfaces';
import { EmptyState, ErrorState, Skeleton, useToast } from '@/components/ui/Overlays';
import { useSession } from '@/session/SessionProvider';
import { useI18n } from '@/i18n';
import { useTheme } from '@/theme/useTheme';
import { formatMoney, formatPeriodRange, isMoneyInput, todayAlmaty } from '@/lib/format';

type Kind = 'ads' | 'other';
const ISO = /^\d{4}-\d{2}-\d{2}$/;

// Расходы магазина на рекламу и прочее (docs/design.md, 12.18).
export default function ExpensesScreen() {
  const { t, locale } = useI18n();
  const { colors, spacing } = useTheme();
  const toast = useToast();
  const { shopId } = useSession();
  const list = useExpenses(shopId);
  const save = useSaveExpense(shopId);
  const del = useDeleteExpense(shopId);
  const [kind, setKind] = useState<Kind>('ads');
  const [amount, setAmount] = useState('');
  const today = todayAlmaty();
  const [from, setFrom] = useState(today.slice(0, 8) + '01');
  const [to, setTo] = useState(today);
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    if (!isMoneyInput(amount) || !amount.trim()) return setError(t('cost.invalid'));
    if (!ISO.test(from) || !ISO.test(to) || from > to) return setError(t('common.errorBody'));
    try {
      await save.mutateAsync({ kind, amount: amount.replace(/\s/g, '').replace(',', '.'), period_start: from, period_end: to });
      toast.show(t('settings.expenseSaved'));
      setAmount('');
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : t('common.unknownError'));
    }
  };

  if (list.isLoading) return <View style={{ padding: spacing.lg }}><Skeleton height={60} radius={16} /></View>;
  if (list.isError) return <ErrorState title={t('common.errorTitle')} onRetry={() => list.refetch()} />;
  const items = list.data?.items ?? [];

  return (
    <ScrollView contentContainerStyle={{ padding: spacing.lg, paddingBottom: 48, gap: spacing.md }} style={{ backgroundColor: colors.bg }} keyboardShouldPersistTaps="handled">
      <Txt variant="footnote" tone="secondary">{t('settings.expensesHint')}</Txt>

      {items.length === 0 ? <EmptyState title={t('settings.expensesEmpty')} /> : (
        <GroupCard>
          {items.map((e, i) => (
            <ListRow
              key={e.id}
              title={`${e.kind === 'ads' ? t('settings.kindAds') : t('settings.kindOther')} · ${formatPeriodRange(e.period_start, e.period_end, locale)}`}
              right={<Txt variant="headline" numeric>{formatMoney(e.amount_minor)}</Txt>}
              onPress={() => del.mutate(e.id)}
              last={i === items.length - 1}
            />
          ))}
        </GroupCard>
      )}

      <Card style={{ gap: spacing.md }}>
        <Txt variant="title3">{t('settings.addExpense')}</Txt>
        <Segmented
          accessibilityLabel={t('settings.addExpense')}
          value={kind}
          options={[{ value: 'ads' as Kind, label: t('settings.kindAds') }, { value: 'other' as Kind, label: t('settings.kindOther') }]}
          onChange={setKind}
        />
        <MoneyField label={t('settings.amount')} value={amount} onChangeText={(v) => { setAmount(v); setError(null); }} error={error} />
        <View style={{ flexDirection: 'row', gap: spacing.md }}>
          <View style={{ flex: 1 }}><TextField label={t('settings.periodFrom')} value={from} onChangeText={setFrom} keyboardType="numbers-and-punctuation" /></View>
          <View style={{ flex: 1 }}><TextField label={t('settings.periodTo')} value={to} onChangeText={setTo} keyboardType="numbers-and-punctuation" /></View>
        </View>
        <Button title={t('common.save')} onPress={submit} loading={save.isPending} fullWidth />
      </Card>
    </ScrollView>
  );
}
