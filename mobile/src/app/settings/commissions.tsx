import { useState } from 'react';
import { ScrollView, View } from 'react-native';

import { useCommissions, useSaveCommission } from '@/api/hooks';
import { ApiError } from '@/api/client';
import { Button } from '@/components/ui/Button';
import { TextField } from '@/components/ui/Inputs';
import { Txt } from '@/components/ui/Text';
import { Badge, Card, GroupCard, ListRow } from '@/components/ui/Surfaces';
import { EmptyState, ErrorState, Skeleton, useToast } from '@/components/ui/Overlays';
import { useSession } from '@/session/SessionProvider';
import { useI18n } from '@/i18n';
import { useTheme } from '@/theme/useTheme';
import { formatPercentBp } from '@/lib/format';

// Комиссии по категориям (docs/design.md, 12.17): ставка в процентах, дата начала, источник.
export default function CommissionsScreen() {
  const { t } = useI18n();
  const { colors, spacing } = useTheme();
  const toast = useToast();
  const { shopId } = useSession();
  const list = useCommissions(shopId);
  const save = useSaveCommission(shopId);
  const [category, setCategory] = useState<string | null>(null);
  const [rate, setRate] = useState('');
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    if (!category) return;
    if (!/^\d{1,3}([.,]\d{1,2})?$/.test(rate.trim())) {
      setError(t('common.errorBody'));
      return;
    }
    try {
      await save.mutateAsync({ category, rate_percent: rate.trim(), effective_from: null });
      toast.show(t('settings.rateSaved'));
      setCategory(null);
      setRate('');
    } catch (e) {
      setError(e instanceof ApiError ? e.message : t('common.unknownError'));
    }
  };

  if (list.isLoading) return <View style={{ padding: spacing.lg, gap: spacing.md }}><Skeleton height={60} radius={16} /></View>;
  if (list.isError) return <ErrorState title={t('common.errorTitle')} onRetry={() => list.refetch()} />;

  const items = list.data?.items ?? [];

  return (
    <ScrollView contentContainerStyle={{ padding: spacing.lg, paddingBottom: 48, gap: spacing.md }} style={{ backgroundColor: colors.bg }}>
      <Txt variant="footnote" tone="secondary">{t('settings.commissionsHint')}</Txt>
      {items.length === 0 ? <EmptyState title={t('settings.commissionsEmpty')} /> : null}
      <GroupCard>
        {items.map((c, i) => (
          <ListRow
            key={c.id}
            title={c.category}
            subtitle={c.effective_from ?? ''}
            right={
              <View style={{ alignItems: 'flex-end', gap: 4 }}>
                <Txt variant="headline" numeric>{formatPercentBp(c.rate_bp)}</Txt>
                <Badge
                  label={c.demo ? t('settings.badgeDemo') : c.verified ? t('settings.badgeVerified') : t('settings.badgeEstimate')}
                  tone={c.demo ? 'primary' : c.verified ? 'success' : 'warning'}
                />
              </View>
            }
            onPress={() => {
              setCategory(c.category);
              setRate((c.rate_bp / 100).toString().replace('.', ','));
            }}
            last={i === items.length - 1}
          />
        ))}
      </GroupCard>

      {category ? (
        <Card style={{ gap: spacing.md }}>
          <Txt variant="title3">{category}</Txt>
          <TextField label={t('settings.rate')} value={rate} onChangeText={(v) => { setRate(v); setError(null); }} keyboardType="decimal-pad" error={error} />
          <Button title={t('common.save')} onPress={submit} loading={save.isPending} fullWidth />
          <Button title={t('common.cancel')} variant="text" onPress={() => setCategory(null)} />
        </Card>
      ) : null}
    </ScrollView>
  );
}
