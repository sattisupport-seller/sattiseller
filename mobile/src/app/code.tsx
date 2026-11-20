import { useLocalSearchParams, useRouter } from 'expo-router';
import { useEffect, useRef, useState } from 'react';
import { Pressable, TextInput, View, type TextInputInstance } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { Button } from '@/components/ui/Button';
import { Txt } from '@/components/ui/Text';
import { ApiError } from '@/api/client';
import { useSession } from '@/session/SessionProvider';
import { useI18n } from '@/i18n';
import { useTheme } from '@/theme/useTheme';

export default function Code() {
  const router = useRouter();
  const { t } = useI18n();
  const { colors, spacing, radii } = useTheme();
  const { email: emailParam, accepted } = useLocalSearchParams<{ email: string; accepted?: string }>();
  const email = String(emailParam ?? '');
  const { verifyCode, requestCode } = useSession();
  const [code, setCode] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [seconds, setSeconds] = useState(60);
  const inputRef = useRef<TextInputInstance>(null);

  useEffect(() => {
    if (seconds <= 0) return;
    const id = setTimeout(() => setSeconds((s) => s - 1), 1000);
    return () => clearTimeout(id);
  }, [seconds]);

  const submit = async (value: string) => {
    if (value.length !== 6 || busy) return;
    setBusy(true);
    setError(null);
    try {
      await verifyCode(email, value, accepted === '1');  // галочка условий стояла на экране входа (1.19)
      router.replace('/');
    } catch (e) {
      setCode('');
      if (e instanceof ApiError && e.code === 'code_expired') setError(t('code.errExpired'));
      else if (e instanceof ApiError && e.code === 'rate_limited') setError(e.message);
      else setError(t('code.errCode'));
    } finally {
      setBusy(false);
    }
  };

  const resend = async () => {
    try {
      await requestCode(email);
      setSeconds(60);
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : t('common.networkError'));
    }
  };

  const digits = code.padEnd(6, ' ').slice(0, 6).split('');

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: colors.bg }} edges={['bottom']}>
      <View style={{ flex: 1, padding: spacing.lg, gap: spacing.lg }}>
        <Txt variant="body" tone="secondary">{t('code.sentTo', { email })}</Txt>

        <Pressable accessibilityLabel={t('code.title')} onPress={() => inputRef.current?.focus()} style={{ flexDirection: 'row', justifyContent: 'space-between' }}>
          {digits.map((d, i) => (
            <View
              key={i}
              style={{
                width: 48,
                height: 56,
                borderRadius: radii.md,
                borderWidth: error || i === code.length ? 2 : 1,
                borderColor: error ? colors.danger : i === code.length ? colors.primary : colors.borderStrong,
                backgroundColor: colors.surface,
                alignItems: 'center',
                justifyContent: 'center',
              }}
            >
              <Txt variant="title2" numeric>{d.trim()}</Txt>
            </View>
          ))}
        </Pressable>
        <TextInput
          ref={inputRef}
          value={code}
          onChangeText={(v) => {
            const clean = v.replace(/\D/g, '').slice(0, 6);
            setCode(clean);
            setError(null);
            if (clean.length === 6) submit(clean);
          }}
          keyboardType="number-pad"
          maxLength={6}
          autoFocus
          textContentType="oneTimeCode"
          autoComplete="sms-otp"
          style={{ position: 'absolute', opacity: 0, height: 1, width: 1 }}
          accessibilityLabel={t('code.title')}
        />

        {error ? <Txt variant="footnote" tone="danger">{error}</Txt> : null}

        <View style={{ gap: spacing.md, marginTop: 'auto' }}>
          {seconds > 0 ? (
            <Txt variant="subhead" tone="tertiary" align="center">{t('code.resend', { time: `0:${String(seconds).padStart(2, '0')}` })}</Txt>
          ) : (
            <Button title={t('code.resendNow')} onPress={resend} variant="text" size="M" />
          )}
          <Button title={t('code.changeEmail')} onPress={() => router.back()} variant="text" size="M" />
          <Button title={t('code.enter')} onPress={() => submit(code)} loading={busy} disabled={code.length !== 6} fullWidth />
        </View>
      </View>
    </SafeAreaView>
  );
}
