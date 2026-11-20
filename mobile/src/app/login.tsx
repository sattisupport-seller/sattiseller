import * as AppleAuthentication from 'expo-apple-authentication';
import * as Crypto from 'expo-crypto';
import { useRouter } from 'expo-router';
import * as Google from 'expo-auth-session/providers/google';
import * as WebBrowser from 'expo-web-browser';
import { useEffect, useState } from 'react';
import { Platform, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { Button } from '@/components/ui/Button';
import { TextField } from '@/components/ui/Inputs';
import { Txt } from '@/components/ui/Text';
import { ApiError, } from '@/api/client';
import { useSession } from '@/session/SessionProvider';
import { useI18n } from '@/i18n';
import { useTheme } from '@/theme/useTheme';

WebBrowser.maybeCompleteAuthSession();

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
// Вход по коду на почту — только для разработки и тестов (ADR-0004). В сборке для магазинов выключен.
const EMAIL_LOGIN = process.env.EXPO_PUBLIC_EMAIL_LOGIN === '1';
const GOOGLE_IOS = process.env.EXPO_PUBLIC_GOOGLE_CLIENT_ID_IOS;
const GOOGLE_ANDROID = process.env.EXPO_PUBLIC_GOOGLE_CLIENT_ID_ANDROID;
const GOOGLE_WEB = process.env.EXPO_PUBLIC_GOOGLE_CLIENT_ID_WEB;
const GOOGLE_CONFIGURED = Boolean(GOOGLE_IOS || GOOGLE_ANDROID || GOOGLE_WEB);

export default function Login() {
  const router = useRouter();
  const { t } = useI18n();
  const { spacing, colors } = useTheme();
  const { requestCode, signInWithIdToken } = useSession();
  const [email, setEmail] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [appleAvailable, setAppleAvailable] = useState(false);

  // Google: токен id_token от провайдера; проверку делает сервер.
  const [googleRequest, googleResponse, promptGoogle] = Google.useIdTokenAuthRequest({
    iosClientId: GOOGLE_IOS,
    androidClientId: GOOGLE_ANDROID,
    webClientId: GOOGLE_WEB,
  });

  useEffect(() => {
    if (Platform.OS !== 'ios') return;
    AppleAuthentication.isAvailableAsync().then(setAppleAvailable).catch(() => setAppleAvailable(false));
  }, []);

  useEffect(() => {
    if (googleResponse?.type !== 'success') return;
    const idToken = googleResponse.params.id_token;
    if (!idToken) {
      setError(t('login.socialFailed'));
      return;
    }
    setBusy(true);
    signInWithIdToken('google', idToken)
      .then(() => router.replace('/'))
      .catch((e) => setError(e instanceof ApiError ? e.message : t('login.socialFailed')))
      .finally(() => setBusy(false));
  }, [googleResponse, signInWithIdToken, router, t]);

  const signInApple = async () => {
    setError(null);
    setBusy(true);
    try {
      // Nonce: Apple получает SHA-256, сервер сравнивает с исходным значением (social_auth.py).
      const raw = Crypto.randomUUID();
      const hashed = await Crypto.digestStringAsync(Crypto.CryptoDigestAlgorithm.SHA256, raw);
      const cred = await AppleAuthentication.signInAsync({
        requestedScopes: [AppleAuthentication.AppleAuthenticationScope.EMAIL],
        nonce: hashed,
      });
      if (!cred.identityToken) throw new Error('no-token');
      await signInWithIdToken('apple', cred.identityToken, raw);
      router.replace('/');
    } catch (e) {
      // Отмена пользователем — не ошибка.
      const code = (e as { code?: string }).code;
      if (code !== 'ERR_REQUEST_CANCELED') setError(e instanceof ApiError ? e.message : t('login.socialFailed'));
    } finally {
      setBusy(false);
    }
  };

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
        {error ? <Txt variant="footnote" tone="danger">{error}</Txt> : null}

        <View style={{ marginTop: 'auto', gap: spacing.md }}>
          {appleAvailable ? (
            <AppleAuthentication.AppleAuthenticationButton
              buttonType={AppleAuthentication.AppleAuthenticationButtonType.SIGN_IN}
              buttonStyle={AppleAuthentication.AppleAuthenticationButtonStyle.BLACK}
              cornerRadius={12}
              style={{ height: 50, width: '100%' }}
              onPress={signInApple}
            />
          ) : null}

          <Button
            title={t('login.withGoogle')}
            variant="secondary"
            onPress={() => { setError(null); void promptGoogle(); }}
            disabled={!GOOGLE_CONFIGURED || !googleRequest}
            loading={busy}
            fullWidth
          />
          {!GOOGLE_CONFIGURED ? <Txt variant="footnote" tone="tertiary" align="center">{t('login.providerNotSet')}</Txt> : null}

          {EMAIL_LOGIN ? (
            <>
              <TextField
                label={t('login.emailLabel')}
                value={email}
                onChangeText={(v) => {
                  setEmail(v);
                  setError(null);
                }}
                placeholder={t('login.emailPlaceholder')}
                keyboardType="email-address"
                returnKeyType="done"
                onSubmitEditing={submit}
                testID="email-input"
              />
              <Txt variant="footnote" tone="tertiary">{t('login.orEmail')}</Txt>
              <Button title={t('login.getCode')} onPress={submit} loading={busy} disabled={!email} fullWidth />
            </>
          ) : null}

          <Txt variant="footnote" tone="tertiary" align="center">{t('welcome.independent')}</Txt>
        </View>
      </View>
    </SafeAreaView>
  );
}
