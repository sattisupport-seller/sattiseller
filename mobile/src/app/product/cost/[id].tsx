import { useLocalSearchParams, useRouter } from 'expo-router';
import { useState } from 'react';
import { Pressable, ScrollView, View } from 'react-native';

import { useCostVersions, useProduct, useSaveCost, useCancelCost, type CostInput } from '@/api/hooks';
import { ApiError } from '@/api/client';
import { Button } from '@/components/ui/Button';
import { MoneyField, TextField } from '@/components/ui/Inputs';
import { Txt } from '@/components/ui/Text';
import { useToast } from '@/components/ui/Overlays';
import { Card } from '@/components/ui/Surfaces';
import { useSession } from '@/session/SessionProvider';
import { useI18n } from '@/i18n';
import { useTheme } from '@/theme/useTheme';
import { formatDayLabel, isMoneyInput, todayAlmaty } from '@/lib/format';

type Mode = 'all' | 'today' | 'date';

// Изменение затрат (docs/design.md, 12.10): поля в тенге, дата начала действия, отмена через тост.
export default function CostScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const { t, locale } = useI18n();
  const { colors, spacing, radii } = useTheme();
  const router = useRouter();
  const toast = useToast();
  const { shopId } = useSession();
  const productId = String(id);
  const product = useProduct(shopId, productId, '30d');
  const versions = useCostVersions(shopId, productId);
  const save = useSaveCost(shopId, productId);
  const cancel = useCancelCost(shopId);
  const hasHistory = (versions.data?.items.length ?? 0) > 0;

  const [purchase, setPurchase] = useState('');
  const [delivery, setDelivery] = useState('');
  const [packaging, setPackaging] = useState('');
  const [other, setOther] = useState('');
  const [mode, setMode] = useState<Mode>(hasHistory ? 'today' : 'all');
  const [date, setDate] = useState('');
  const [error, setError] = useState<string | null>(null);
  const today = todayAlmaty();
  const soldCount = product.data?.product.sold_qty ?? 0;

  const valid = (v: string) => v === '' || isMoneyInput(v);
  const submit = async () => {
    if (!purchase.trim() || !isMoneyInput(purchase)) {
      setError(t('cost.invalid'));
      return;
    }
    if (![delivery, packaging, other].every(valid)) {
      setError(t('common.errorBody'));
      return;
    }
    if (mode === 'date' && !/^\d{4}-\d{2}-\d{2}$/.test(date)) {
      setError(t('common.errorBody'));
      return;
    }
    const body: CostInput = {
      purchase: purchase.replace(/\s/g, '').replace(',', '.'),
      delivery_to_warehouse: (delivery || '0').replace(/\s/g, '').replace(',', '.'),
      packaging: (packaging || '0').replace(/\s/g, '').replace(',', '.'),
      other: (other || '0').replace(/\s/g, '').replace(',', '.'),
      apply_to_history: mode === 'all' ? true : mode === 'today' ? false : null,
      effective_from: mode === 'date' ? date : null,
    };
    setError(null);
    try {
      const created = await save.mutateAsync(body);
      toast.show(t('cost.saved'), {
        label: t('cost.undo'),
        onPress: () => cancel.mutate(created.id),
      });
      router.back();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : t('common.unknownError'));
    }
  };

  return (
    <ScrollView contentContainerStyle={{ padding: spacing.lg, paddingBottom: 48, gap: spacing.lg }} style={{ backgroundColor: colors.bg }}>
      <Txt variant="footnote" tone="tertiary">{t('cost.unitHint')}</Txt>
      <MoneyField label={t('cost.purchase')} value={purchase} onChangeText={(v) => { setPurchase(v); setError(null); }} error={error} />
      <MoneyField label={t('cost.deliveryWh')} value={delivery} onChangeText={setDelivery} />
      <MoneyField label={t('cost.packaging')} value={packaging} onChangeText={setPackaging} />
      <MoneyField label={t('cost.other')} value={other} onChangeText={setOther} />

      <View style={{ gap: spacing.sm }}>
        <Txt variant="footnoteStrong" tone="secondary">{t('cost.effectiveFrom')}</Txt>
        {([
          { value: 'all', label: t('cost.allHistory'), show: !hasHistory },
          { value: 'today', label: t('cost.fromToday'), show: true },
          { value: 'date', label: t('cost.pickDate'), show: true },
        ] as { value: Mode; label: string; show: boolean }[])
          .filter((o) => o.show)
          .map((o) => (
            <Pressable
              key={o.value}
              accessibilityRole="radio"
              accessibilityState={{ selected: mode === o.value }}
              onPress={() => setMode(o.value)}
              style={{
                minHeight: 48,
                borderRadius: radii.md,
                borderWidth: 1,
                borderColor: mode === o.value ? colors.primary : colors.border,
                backgroundColor: mode === o.value ? colors.primarySoft : colors.surface,
                paddingHorizontal: spacing.lg,
                flexDirection: 'row',
                alignItems: 'center',
                justifyContent: 'space-between',
              }}
            >
              <Txt variant="bodyMedium">{o.label}</Txt>
              <View style={{ width: 20, height: 20, borderRadius: 10, borderWidth: 2, borderColor: mode === o.value ? colors.primary : colors.borderStrong, backgroundColor: mode === o.value ? colors.primary : 'transparent' }} />
            </Pressable>
          ))}
        {mode === 'date' ? (
          <TextField value={date} onChangeText={setDate} placeholder="2026-11-19" keyboardType="numbers-and-punctuation" />
        ) : null}
      </View>

      <Card>
        <Txt variant="subhead" tone="secondary">
          {t('cost.recalc', { count: soldCount })}
          {mode === 'today' ? ` · ${formatDayLabel(today, today, locale)}` : ''}
        </Txt>
      </Card>

      <Button title={t('common.save')} onPress={submit} loading={save.isPending} fullWidth />
    </ScrollView>
  );
}
