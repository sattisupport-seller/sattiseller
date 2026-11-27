// 1.19: повторное согласие для уже вошедших, когда версия условий и политики изменилась.
import { useRouter } from 'expo-router';
import { useState } from 'react';
import { Linking, Pressable, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { useAppConfig } from '@/api/hooks';
import { ApiError } from '@/api/client';
import { Button } from '@/components/ui/Button';
import { Txt } from '@/components/ui/Text';
import { useSession } from '@/session/SessionProvider';
import { useI18n } from '@/i18n';
import { useTheme } from '@/theme/useTheme';

export default function TermsConsent() {
  const router = useRouter();
  const { t } = useI18n();
  const { spacing, colors } = useTheme();
  const { acceptTerms } = useSession();
  const config = useAppConfig();
  const [accepted, setAccepted] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    if (!accepted) return;
    setBusy(true);
    setError(null);
    try {
      await acceptTerms();
      router.replace('/');
    } catch (e) {
      setError(e instanceof ApiError ? e.message : t('consent.failed'));
    } finally {
      setBusy(false);
    }
  };

  const openLink = (url: string | undefined) => {
    if (url) void Linking.openURL(url);
  };

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: colors.bg }} edges={['bottom']}>
      <View style={{ flex: 1, padding: spacing.lg, gap: spacing.lg }}>
        <Txt variant="title2">{t('consent.title')}</Txt>
        <Txt variant="body">{t('consent.text')}</Txt>

        <View style={{ flexDirection: 'row', gap: spacing.md, flexWrap: 'wrap' }}>
          <Pressable accessibilityRole="link" onPress={() => openLink(config.data?.privacy_url)}>
            <Txt variant="footnote" tone="secondary">{t('login.privacyLink')}</Txt>
          </Pressable>
          <Pressable accessibilityRole="link" onPress={() => openLink(config.data?.terms_url)}>
            <Txt variant="footnote" tone="secondary">{t('login.termsLink')}</Txt>
          </Pressable>
        </View>

        <View style={{ marginTop: 'auto', gap: spacing.md }}>
          {error ? <Txt variant="footnote" tone="danger">{error}</Txt> : null}
          <Pressable
            accessibilityRole="checkbox"
            accessibilityState={{ checked: accepted }}
            accessibilityLabel={t('login.acceptLabel')}
            onPress={() => { setAccepted((v) => !v); setError(null); }}
            style={{ flexDirection: 'row', gap: spacing.sm, alignItems: 'flex-start' }}
          >
            <Txt variant="footnote">{accepted ? '☑' : '☐'}</Txt>
            <Txt variant="footnote" style={{ flex: 1 }}>{t('login.acceptLabel')}</Txt>
          </Pressable>
          {/* К-24: согласие на ИИ входит в эту галочку — отдельной строкой рядом с ней (Apple 5.1.2(i)) */}
          <Txt variant="footnote" tone="secondary">{t('login.aiNote')}</Txt>
          <Button title={t('consent.accept')} onPress={submit} loading={busy} disabled={!accepted || busy} fullWidth />
        </View>
      </View>
    </SafeAreaView>
  );
}
