import { useRouter } from 'expo-router';
import { useEffect, useState } from 'react';
import { ScrollView, View } from 'react-native';

import { ApiError } from '@/api/client';
import { useDeactivateConfirm, useDeleteAccountConfirm, useDeleteAccountStart } from '@/api/hooks';
import { Button } from '@/components/ui/Button';
import { TextField } from '@/components/ui/Inputs';
import { Txt } from '@/components/ui/Text';
import { Banner, Card } from '@/components/ui/Surfaces';
import { openManageSubscriptions } from '@/lib/purchases';
import { useSession } from '@/session/SessionProvider';
import { useI18n } from '@/i18n';
import { useTheme } from '@/theme/useTheme';

// Удаление аккаунта с подтверждением кодом из письма (docs/spec.md, 12.1 и 12.22).
// К-21 (решения владельца 23.11.2026): предупреждение и два варианта — удалить всё сразу или деактивировать на 30 дней.
// Полное удаление доступно всегда (Apple 5.1.1(v), Google Play); подписка в магазине сама не отменяется.
export default function DeleteAccountScreen() {
  const { t } = useI18n();
  const { colors, spacing } = useTheme();
  const router = useRouter();
  const { email, logout } = useSession();
  const start = useDeleteAccountStart();
  const confirm = useDeleteAccountConfirm();
  const deactivate = useDeactivateConfirm();
  const [sent, setSent] = useState(false);
  const [code, setCode] = useState('');
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    start.mutate(undefined, {
      onSuccess: () => setSent(true),
      onError: (e) => setError(e instanceof ApiError ? e.message : t('common.networkError')),
    });
    // отправляем код один раз при открытии экрана
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const submit = async () => {
    if (code.length !== 6) return;
    try {
      await confirm.mutateAsync(code);
      await logout();
      router.replace('/welcome');
    } catch (e) {
      setError(e instanceof ApiError ? e.message : t('common.unknownError'));
    }
  };

  const submitDeactivate = async () => {
    if (code.length !== 6) return;
    try {
      await deactivate.mutateAsync(code);
      router.replace('/account-deactivated' as never);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : t('common.unknownError'));
    }
  };

  const busy = confirm.isPending || deactivate.isPending;

  return (
    <ScrollView contentContainerStyle={{ padding: spacing.lg, paddingBottom: 48, gap: spacing.lg }} style={{ backgroundColor: colors.bg }}>
      <Banner text={t('settings.deleteWarn')} tone="danger" />
      <Card style={{ gap: spacing.sm }}>
        <Txt variant="bodyMedium">{t('settings.deleteWhat')}</Txt>
      </Card>
      <Banner text={t('settings.deleteSubscriptionNote')} tone="warning" />
      <Button title={t('subscription.manage')} variant="text" onPress={() => { void openManageSubscriptions('satti_monthly'); }} fullWidth />
      <Banner text={t('settings.deletePriceNote')} tone="warning" />

      {sent && email ? <Txt variant="subhead" tone="secondary">{t('settings.deleteCodeSent', { email })}</Txt> : null}
      <Txt variant="subhead" tone="secondary">{t('settings.deleteChoose')}</Txt>
      <TextField
        label="Код"
        value={code}
        onChangeText={(v) => { setCode(v.replace(/\D/g, '').slice(0, 6)); setError(null); }}
        keyboardType="number-pad"
        maxLength={6}
        error={error}
      />
      <View style={{ gap: spacing.md }}>
        <Button title={t('settings.deleteConfirm')} variant="destructive" fullWidth onPress={submit}
                disabled={code.length !== 6 || busy} loading={confirm.isPending} />
        <Txt variant="footnote" tone="secondary">{t('settings.deactivateWhat')}</Txt>
        <Button title={t('settings.deactivateConfirm')} variant="secondary" fullWidth onPress={submitDeactivate}
                disabled={code.length !== 6 || busy} loading={deactivate.isPending} />
      </View>
    </ScrollView>
  );
}
