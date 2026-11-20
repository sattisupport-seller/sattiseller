import { useState } from 'react';
import { ScrollView, Switch, View } from 'react-native';

import { useSaveTax, useTax } from '@/api/hooks';
import { ApiError } from '@/api/client';
import { Button } from '@/components/ui/Button';
import { TextField } from '@/components/ui/Inputs';
import { Txt } from '@/components/ui/Text';
import { Chip, GroupCard, ListRow, Card } from '@/components/ui/Surfaces';
import { ErrorState, Skeleton, useToast } from '@/components/ui/Overlays';
import { useSession } from '@/session/SessionProvider';
import { useI18n } from '@/i18n';
import { useTheme } from '@/theme/useTheme';
import { formatPercentBp, todayAlmaty } from '@/lib/format';

// Налог (ТЗ 2.1, раздел 7.3; design 12.26): переключатель, ставка, дата начала, история версий.
export default function TaxScreen() {
  const { t } = useI18n();
  const { colors, spacing } = useTheme();
  const toast = useToast();
  const { shopId } = useSession();
  const tax = useTax(shopId);
  const save = useSaveTax(shopId);
  const [draft, setDraft] = useState<{ enabled: boolean; rate: string } | null>(null);
  const [from, setFrom] = useState<'all' | 'today'>('all');
  const [error, setError] = useState<string | null>(null);

  if (tax.isLoading) return <View style={{ padding: spacing.lg, gap: spacing.md }}><Skeleton height={60} radius={16} /></View>;
  if (tax.isError) return <ErrorState title={t('common.errorTitle')} onRetry={() => tax.refetch()} />;

  const current = tax.data?.current ?? null;
  const view = draft ?? {
    enabled: current?.enabled ?? false,
    rate: current?.rate_bp != null ? String(current.rate_bp / 100).replace('.', ',') : '',
  };

  const submit = async () => {
    setError(null);
    if (view.enabled && !/^(30([.,]0)?|([0-2]?\d)([.,]\d)?)$/.test(view.rate.trim())) {
      setError(t('tax.invalid'));
      return;
    }
    try {
      await save.mutateAsync({
        enabled: view.enabled,
        rate_percent: view.enabled ? view.rate.trim() : null,
        effective_from: from === 'today' ? todayAlmaty() : null,
      });
      toast.show(t('tax.saved'));
      setDraft(null);
      setFrom('all');
    } catch (e) {
      setError(e instanceof ApiError ? e.message : t('common.unknownError'));
    }
  };

  const items = tax.data?.items ?? [];

  return (
    <ScrollView contentContainerStyle={{ padding: spacing.lg, paddingBottom: 48, gap: spacing.md }} style={{ backgroundColor: colors.bg }}>
      <Txt variant="footnote" tone="secondary">{t('tax.hint')}</Txt>

      <Card style={{ gap: spacing.md }}>
        <View style={{ flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', minHeight: 44 }}>
          <Txt variant="body" style={{ flex: 1 }}>{t('tax.enabled')}</Txt>
          <Switch
            accessibilityLabel={t('tax.enabled')}
            value={view.enabled}
            onValueChange={(v) => { setDraft({ ...view, enabled: v }); setError(null); }}
            trackColor={{ false: colors.borderStrong, true: colors.primary }}
          />
        </View>

        {view.enabled ? (
          <>
            <TextField
              label={t('tax.rate')}
              value={view.rate}
              onChangeText={(v) => { setDraft({ ...view, rate: v }); setError(null); }}
              keyboardType="decimal-pad"
              error={error}
            />
            <Txt variant="subheadMedium" tone="secondary">{t('tax.from')}</Txt>
            <View style={{ flexDirection: 'row', flexWrap: 'wrap' }}>
              <Chip label={t('tax.fromAll')} selected={from === 'all'} onPress={() => setFrom('all')} />
              <Chip label={t('tax.fromToday')} selected={from === 'today'} onPress={() => setFrom('today')} />
            </View>
          </>
        ) : null}
        {!view.enabled && error ? <Txt variant="footnote" tone="danger">{error}</Txt> : null}

        <Button title={t('common.save')} onPress={submit} loading={save.isPending} fullWidth />
      </Card>

      {items.length > 0 ? (
        <>
          <Txt variant="subheadMedium" tone="secondary">{t('tax.history')}</Txt>
          <GroupCard>
            {items.map((row, i) => (
              <ListRow
                key={row.id}
                title={row.enabled ? formatPercentBp(row.rate_bp) : t('tax.off')}
                subtitle={row.effective_from ?? t('tax.fromAll')}
                right={i === 0 && row.enabled ? <Txt variant="footnote" tone="tertiary">{t('tax.current')}</Txt> : undefined}
                last={i === items.length - 1}
              />
            ))}
          </GroupCard>
        </>
      ) : null}
    </ScrollView>
  );
}
