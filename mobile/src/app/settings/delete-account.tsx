import { useRouter } from 'expo-router';
import { useEffect, useState } from 'react';
import { ScrollView, View } from 'react-native';

import { ApiError } from '@/api/client';
import { useDeleteAccountConfirm, useDeleteAccountStart } from '@/api/hooks';
import { Button } from '@/components/ui/Button';
import { TextField } from '@/components/ui/Inputs';
import { Txt } from '@/components/ui/Text';
import { Banner, Card } from '@/components/ui/Surfaces';
import { useSession } from '@/session/SessionProvider';
import { useI18n } from '@/i18n';
import { useTheme } from '@/theme/useTheme';

// Удаление аккаунта с подтверждением кодом из письма (docs/spec.md, 12.1 и 12.22).
export default function DeleteAccountScreen() {
  const { t } = useI18n();
  const { colors, spacing } = useTheme();
  const router = useRouter();
  const { email, logout } = useSession();
  const start = useDeleteAccountStart();
  const confirm = useDeleteAccountConfirm();
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

  return (
    <ScrollView contentContainerStyle={{ padding: spacing.lg, paddingBottom: 48, gap: spacing.lg }} style={{ backgroundColor: colors.bg }}>
      <Card>
        <Txt variant="bodyMedium">{t('settings.deleteWhat')}</Txt>
      </Card>
      {sent && email ? <Txt variant="subhead" tone="secondary">{t('settings.deleteCodeSent', { email })}</Txt> : null}
      <TextField
        label="Код"
        value={code}
        onChangeText={(v) => { setCode(v.replace(/\D/g, '').slice(0, 6)); setError(null); }}
        keyboardType="number-pad"
        maxLength={6}
        error={error}
      />
      <Banner text={t('settings.deleteWarn')} tone="danger" />
      <View style={{ marginTop: spacing.md }}>
        <Button title={t('settings.deleteConfirm')} variant="destructive" fullWidth onPress={submit} disabled={code.length !== 6} loading={confirm.isPending} />
      </View>
    </ScrollView>
  );
}
