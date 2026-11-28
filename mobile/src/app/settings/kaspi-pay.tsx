import * as DocumentPicker from 'expo-document-picker';
import { Stack } from 'expo-router';
import { useState } from 'react';
import { ScrollView } from 'react-native';

import { ApiError } from '@/api/client';
import { useKaspiPayReport, type KaspiPayResult } from '@/api/hooks';
import { Button } from '@/components/ui/Button';
import { Card, GroupCard, ListRow } from '@/components/ui/Surfaces';
import { Txt } from '@/components/ui/Text';
import { useI18n } from '@/i18n';
import { formatMoney } from '@/lib/format';
import { useSession } from '@/session/SessionProvider';
import { useTheme } from '@/theme/useTheme';
import { filePart } from '@/api/upload';

// К-33 Б1: сверка с Kaspi — выгрузка Kaspi Pay «Продажи» (Excel) против расчёта Satti по каждому заказу.
export default function KaspiPayScreen() {
  const { t } = useI18n();
  const { colors, spacing } = useTheme();
  const { shopId } = useSession();
  const upload = useKaspiPayReport(shopId);
  const [result, setResult] = useState<KaspiPayResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const pick = async () => {
    setError(null);
    const res = await DocumentPicker.getDocumentAsync({
      type: ['application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', 'text/csv', 'text/comma-separated-values'],
      copyToCacheDirectory: true,
    });
    if (res.canceled || !res.assets?.[0]) return;
    const asset = res.assets[0];
    const form = new FormData();
    form.append('file', filePart(asset.uri, asset.name, asset.mimeType ?? 'application/octet-stream'));
    try {
      setResult(await upload.mutateAsync(form));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : t('common.unknownError'));
    }
  };

  const fieldName = (f: string) => t(`kaspiPay.field_${f}` as never);

  return (
    <ScrollView contentContainerStyle={{ padding: spacing.lg, gap: spacing.md, paddingBottom: 48 }} style={{ backgroundColor: colors.bg }}>
      <Stack.Screen options={{ title: t('kaspiPay.title') }} />
      <Txt variant="footnote" tone="secondary">{t('kaspiPay.hint')}</Txt>
      <Button title={t('kaspiPay.pick')} onPress={pick} loading={upload.isPending} fullWidth />
      {error ? <Txt variant="footnote" tone="danger">{error}</Txt> : null}
      {result ? (
        <>
          <Card style={{ gap: spacing.xs }}>
            <Txt variant="headline">
              {result.mismatch_orders === 0
                ? t('kaspiPay.allMatch', { count: result.matched })
                : t('kaspiPay.summary', { matched: result.matched, sum: formatMoney(result.mismatch_sum_minor), count: result.mismatch_orders })}
            </Txt>
            {result.missing_in_satti_count > 0 ? (
              <Txt variant="footnote" tone="secondary">{t('kaspiPay.missing', { count: result.missing_in_satti_count })}</Txt>
            ) : null}
            {result.bad_rows.length > 0 ? (
              <Txt variant="footnote" tone="secondary">{t('kaspiPay.badRows', { rows: result.bad_rows.join(', ') })}</Txt>
            ) : null}
          </Card>
          {result.mismatches.length > 0 ? (
            <GroupCard>
              {result.mismatches.slice(0, 30).map((m, i) => (
                <ListRow
                  key={`${m.order_number}-${m.field}`}
                  title={`${m.order_number} · ${fieldName(m.field)}`}
                  subtitle={t('kaspiPay.row', { satti: formatMoney(m.satti_minor), kaspi: formatMoney(m.kaspi_minor), diff: formatMoney(m.diff_minor, 'auto') })}
                  last={i === Math.min(result.mismatches.length, 30) - 1}
                />
              ))}
            </GroupCard>
          ) : null}
        </>
      ) : null}
    </ScrollView>
  );
}
