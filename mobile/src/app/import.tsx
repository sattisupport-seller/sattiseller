import { File, Paths } from 'expo-file-system';
import * as Sharing from 'expo-sharing';
import * as DocumentPicker from 'expo-document-picker';
import { useRouter } from 'expo-router';
import { FileSpreadsheet, FileDown, CircleCheck } from 'lucide-react-native';
import { useState } from 'react';
import { Linking, ScrollView, Switch, View } from 'react-native';

import { useImportApply, useImportMapping, useImportPreview, useImportUndo, useImportUpload } from '@/api/hooks';
import { API_URL } from '@/config';
import { ApiError, request } from '@/api/client';
import { Button } from '@/components/ui/Button';
import { Chip, Card, Badge, Stepper, GroupCard, ListRow, SuccessMark, Banner } from '@/components/ui/Surfaces';
import { Txt } from '@/components/ui/Text';
import { useToast } from '@/components/ui/Overlays';
import { useSession } from '@/session/SessionProvider';
import { useI18n } from '@/i18n';
import { useTheme } from '@/theme/useTheme';
import { useQueryClient } from '@tanstack/react-query';
import { filePart } from '@/api/upload';

type UploadState = {
  id: string;
  filename: string;
  columns: string[];
  rows_total: number;
  mapping: Record<string, string | null>;
  sample: string[][];
};

const FIELD_KEYS = ['sku', 'purchase', 'delivery_to_warehouse', 'packaging', 'other', 'effective_from'] as const;
const FIELD_LABEL: Record<(typeof FIELD_KEYS)[number], 'fieldSku' | 'fieldPurchase' | 'fieldDelivery' | 'fieldPackaging' | 'fieldOther' | 'fieldEffective'> = {
  sku: 'fieldSku',
  purchase: 'fieldPurchase',
  delivery_to_warehouse: 'fieldDelivery',
  packaging: 'fieldPackaging',
  other: 'fieldOther',
  effective_from: 'fieldEffective',
};

// Импорт затрат (docs/design.md, 12.12): 4 шага и результат; отмена последней загрузки.
export default function ImportScreen() {
  const { t, locale } = useI18n();
  const { colors, spacing } = useTheme();
  const router = useRouter();
  const toast = useToast();
  const qc = useQueryClient();
  const { shopId } = useSession();
  const upload = useImportUpload(shopId);
  const mapping = useImportMapping(shopId);
  const apply = useImportApply(shopId);
  const undo = useImportUndo(shopId);

  const [step, setStep] = useState<1 | 2 | 3 | 4 | 5>(1);
  const [file, setFile] = useState<UploadState | null>(null);
  const [draft, setDraft] = useState<Record<string, string | null>>({});
  const [error, setError] = useState<string | null>(null);
  const [applyAll, setApplyAll] = useState(true);
  const [duplicates] = useState<'skip' | 'last'>('skip');
  const [applied, setApplied] = useState<{ rows: number; importId: string } | null>(null);
  const preview = useImportPreview(shopId, file?.id ?? null, step === 4);

  const pick = async () => {
    setError(null);
    const res = await DocumentPicker.getDocumentAsync({
      type: [
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        'text/csv',
        'text/comma-separated-values',
      ],
      copyToCacheDirectory: true,
    });
    if (res.canceled || !res.assets?.[0]) return;
    const asset = res.assets[0];
    const name = asset.name.toLowerCase();
    if (!name.endsWith('.xlsx') && !name.endsWith('.csv')) {
      setError(t('imp.badFile'));
      return;
    }
    const form = new FormData();
    form.append('file', filePart(asset.uri, asset.name, asset.mimeType ?? 'application/octet-stream'));
    try {
      const data = await upload.mutateAsync(form);
      setFile({ ...data, sample: (data as unknown as { sample: string[][] }).sample ?? [] });
      setDraft(data.mapping);
      setStep(3);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : t('common.unknownError'));
    }
  };

  const confirmMapping = async () => {
    if (!file) return;
    if (!draft.sku || !draft.purchase) {
      setError(t('imp.needMapping'));
      return;
    }
    try {
      await mapping.mutateAsync({ importId: file.id, mapping: draft, duplicates });
      setStep(4);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : t('common.unknownError'));
    }
  };

  const doApply = async () => {
    if (!file) return;
    try {
      const res = await apply.mutateAsync({ importId: file.id, applyToHistory: applyAll });
      setApplied({ rows: res.applied_rows, importId: file.id });
      setStep(5);
      toast.show(t('imp.s5'));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : t('common.unknownError'));
    }
  };

  const doUndo = async () => {
    if (!applied) return;
    try {
      await undo.mutateAsync(applied.importId);
      toast.show(t('imp.undone'));
      router.back();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : t('common.unknownError'));
    }
  };

  // Файл ошибок импорта (CSV) во временной папке и меню «Поделиться» (spec-2.1, задача 17).
  const copyErrors = async () => {
    if (!file) return;
    try {
      const csv = await request<string>(`/shops/${shopId}/imports/${file.id}/errors`, { text: true });
      const target = new File(Paths.cache, `import-errors-${file.id}.csv`);
      if (target.exists) target.delete();
      target.create();
      await target.write(csv);
      if (!(await Sharing.isAvailableAsync())) {
        setError(t('common.unknownError'));
        return;
      }
      await Sharing.shareAsync(target.uri, { mimeType: 'text/csv', UTI: 'public.comma-separated-values-text' });
    } catch {
      setError(t('common.unknownError'));
    }
  };

  const stepName = ['', t('imp.s1'), t('imp.s2'), t('imp.s3'), t('imp.s4'), t('imp.s5')][step];

  return (
    <ScrollView contentContainerStyle={{ padding: spacing.lg, paddingBottom: 140, gap: spacing.lg }} style={{ backgroundColor: colors.bg }}>
      {step < 5 ? (
        <View style={{ gap: spacing.sm }}>
          <Stepper step={step} total={4} />
          <Txt variant="footnote" tone="tertiary">{t('imp.step', { n: step, name: stepName })}</Txt>
        </View>
      ) : null}

      {step === 1 ? (
        <>
          <Txt variant="title3">{t('imp.s1')}</Txt>
          <GroupCard>
            <ListRow title={t('imp.s1a')} last={false} />
            <ListRow title={t('imp.s1b')} last={false} />
            <ListRow title={t('imp.s1c')} last />
          </GroupCard>
          <Button title={t('imp.pickFile')} onPress={() => setStep(2)} fullWidth icon={<FileSpreadsheet size={20} color={colors.onPrimary} />} />
          <Button title={t('imp.downloadTemplate')} variant="text" onPress={() => Linking.openURL(`${API_URL}/templates/costs`)} icon={<FileDown size={18} color={colors.primary} />} />
        </>
      ) : null}

      {step === 2 ? (
        <>
          <Txt variant="title3">{t('imp.s2')}</Txt>
          {upload.isPending ? <Txt variant="body" tone="secondary">{t('imp.uploading')}</Txt> : null}
          <Button title={t('imp.pickFile')} onPress={pick} fullWidth loading={upload.isPending} />
          {error ? <Banner text={error} tone="danger" action={t('imp.chooseOther')} onAction={pick} /> : null}
        </>
      ) : null}

      {step === 3 && file ? (
        <>
          <Txt variant="title3">{t('imp.s3')}</Txt>
          <Txt variant="footnote" tone="secondary">{t('imp.s3hint')}</Txt>
          <Card>
            <Txt variant="bodyMedium">{file.filename}</Txt>
            <Txt variant="footnote" tone="tertiary">{formatCountRows(file.rows_total)}</Txt>
          </Card>
          {FIELD_KEYS.map((key) => (
            <View key={key} style={{ gap: 8 }}>
              <Txt variant="subheadMedium" tone="secondary">{t(`imp.${FIELD_LABEL[key]}`)}</Txt>
              <ScrollView horizontal showsHorizontalScrollIndicator={false}>
                <Chip label={t('imp.s3skip')} selected={!draft[key]} onPress={() => setDraft((d) => ({ ...d, [key]: null }))} />
                {file.columns.map((c) => (
                  <Chip key={c} label={c || '—'} selected={draft[key] === c} onPress={() => setDraft((d) => ({ ...d, [key]: c }))} />
                ))}
              </ScrollView>
            </View>
          ))}
          {file.sample.length > 0 ? (
            <Card>
              <Txt variant="footnoteStrong" tone="secondary">{file.columns.join(' · ')}</Txt>
              {file.sample.map((row, i) => (
                <Txt key={i} variant="footnote" tone="tertiary" numeric>{row.join(' · ')}</Txt>
              ))}
            </Card>
          ) : null}
          {error ? <Txt variant="footnote" tone="danger">{error}</Txt> : null}
          <Button title={t('common.next')} onPress={confirmMapping} fullWidth loading={mapping.isPending} />
        </>
      ) : null}

      {step === 4 ? (
        <>
          <Txt variant="title3">{t('imp.s4')}</Txt>
          {preview.isLoading ? <Txt variant="body" tone="secondary">{t('common.loading')}</Txt> : null}
          {preview.data ? (
            <>
              <View style={{ flexDirection: 'row', gap: 8 }}>
                <Stat title={t('imp.newCosts')} value={String(preview.data.counts.new)} tone="success" />
                <Stat title={t('imp.updates')} value={String(preview.data.counts.updated)} tone="warning" />
              </View>
              <View style={{ flexDirection: 'row', gap: 8 }}>
                <Stat title={t('imp.unchanged')} value={String(preview.data.counts.unchanged)} />
                <Stat title={t('imp.errorsCount')} value={String(preview.data.errors_count)} tone="danger" />
              </View>
              {preview.data.new_products_without_cost > 0 ? (
                <Card style={{ gap: spacing.sm }}>
                  <Txt variant="title3">{t('imp.firstLoad')}</Txt>
                  <Txt variant="footnote" tone="secondary">{t('imp.firstLoadHint', { count: preview.data.new_products_without_cost })}</Txt>
                  <View style={{ flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' }}>
                    <Txt variant="bodyMedium">{t('quickCost.applyAll')}</Txt>
                    <Switch value={applyAll} onValueChange={setApplyAll} trackColor={{ true: colors.primary }} accessibilityLabel={t('quickCost.applyAll')} />
                  </View>
                </Card>
              ) : null}
              <Card style={{ gap: spacing.sm }}>
                <Txt variant="footnoteStrong" tone="secondary">{t('imp.errorsTitle', { count: preview.data.errors_count })}</Txt>
                <Txt variant="footnote" tone="secondary">{t('imp.errorsHint')}</Txt>
                {preview.data.errors.map((e, i) => (
                  <View key={`${e.row}-${i}`} style={{ gap: 2 }}>
                    <Txt variant="footnoteStrong">{t('imp.errorRow', { row: e.row })}{e.sku ? ` · ${e.sku}` : ''}</Txt>
                    <Txt variant="footnote" tone="danger">{e.message}</Txt>
                  </View>
                ))}
                {preview.data.errors_count > preview.data.errors.length ? (
                  <Txt variant="footnote" tone="tertiary">+{preview.data.errors_count - preview.data.errors.length}</Txt>
                ) : null}
                {preview.data.errors_count > 0 ? (
                  <Button title={t('imp.downloadErrors')} variant="text" size="M" onPress={copyErrors} />
                ) : null}
              </Card>
              {error ? <Txt variant="footnote" tone="danger">{error}</Txt> : null}
              <View style={{ position: 'absolute', left: 0, right: 0, bottom: 0, padding: spacing.lg, backgroundColor: colors.surface, borderTopWidth: 1, borderTopColor: colors.divider }}>
                <Button
                  title={t('imp.loadN', { count: preview.data.valid_rows })}
                  onPress={doApply}
                  loading={apply.isPending}
                  disabled={preview.data.valid_rows === 0}
                  fullWidth
                />
              </View>
            </>
          ) : null}
        </>
      ) : null}

      {step === 5 && applied ? (
        <View style={{ alignItems: 'center', gap: spacing.md, paddingTop: spacing['3xl'] }}>
          <SuccessMark />
          <Txt variant="title2" align="center">{t('imp.s5')}</Txt>
          <Badge label={`${applied.rows}`} tone="success" icon={<CircleCheck size={12} color={colors.onSuccessSoft} />} />
          <Button title={t('imp.toProducts')} onPress={() => { qc.invalidateQueries(); router.back(); }} fullWidth />
          <Button title={t('imp.undoLoad')} variant="text" onPress={doUndo} loading={undo.isPending} />
          {error ? <Txt variant="footnote" tone="danger">{error}</Txt> : null}
        </View>
      ) : null}

    </ScrollView>
  );
}

function formatCountRows(n: number): string {
  return `${n} строк`;
}

function Stat({ title, value, tone }: { title: string; value: string; tone?: 'success' | 'warning' | 'danger' }) {
  const { colors, spacing, radii } = useTheme();
  const c = tone === 'success' ? colors.success : tone === 'warning' ? colors.warning : tone === 'danger' ? colors.danger : colors.textPrimary;
  return (
    <View style={{ flex: 1, backgroundColor: colors.surface, borderRadius: radii.md, borderWidth: 1, borderColor: colors.border, padding: spacing.md, gap: 4 }}>
      <Txt variant="footnote" tone="secondary">{title}</Txt>
      <Txt variant="title2" numeric style={{ color: c }}>{value}</Txt>
    </View>
  );
}
