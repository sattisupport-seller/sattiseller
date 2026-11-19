import { useRouter } from 'expo-router';
import { useState } from 'react';
import { View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { Button } from '@/components/ui/Button';
import { TextField } from '@/components/ui/Inputs';
import { Txt } from '@/components/ui/Text';
import { ApiError, } from '@/api/client';
import { useSession } from '@/session/SessionProvider';
import { useI18n } from '@/i18n';
import { useTheme } from '@/theme/useTheme';

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export default function Login() {
  const router = useRouter();
  const { t } = useI18n();
  const { spacing, colors } = useTheme();
  const { requestCode } = useSession();
  const [email, setEmail] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    const value = email.trim().toLowerCase();
    if (!EMAIL_RE.test(value)) {
      setError(t('login.errEmail'));
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await requestCode(value);
      router.push({ pathname: '/code', params: { email: value } });
    } catch (e) {
      if (e instanceof ApiError && e.status === 429) setError(t('login.tooMany'));
      else setError(e instanceof ApiError ? e.message : t('common.networkError'));
    } finally {
      setBusy(false);
    }
  };

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: colors.bg }} edges={['bottom']}>
      <View style={{ flex: 1, padding: spacing.lg, gap: spacing.lg }}>
        <TextField
          label={t('login.emailLabel')}
          value={email}
          onChangeText={(v) => {
            setEmail(v);
            setError(null);
          }}
          placeholder={t('login.emailPlaceholder')}
          keyboardType="email-address"
          autoFocus
          error={error}
          returnKeyType="done"
          onSubmitEditing={submit}
          testID="email-input"
        />
        <View style={{ marginTop: 'auto', gap: spacing.md }}>
          <Button title={t('login.getCode')} onPress={submit} loading={busy} disabled={!email} fullWidth />
          <Txt variant="footnote" tone="tertiary" align="center">{t('welcome.independent')}</Txt>
        </View>
      </View>
    </SafeAreaView>
  );
}
