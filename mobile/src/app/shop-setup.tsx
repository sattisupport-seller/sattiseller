import { useRouter } from 'expo-router';
import { useState } from 'react';
import { View, Pressable } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { Button } from '@/components/ui/Button';
import { TextField } from '@/components/ui/Inputs';
import { Txt } from '@/components/ui/Text';
import { Card } from '@/components/ui/Surfaces';
import { errorMessage, useSession } from '@/session/SessionProvider';
import { useI18n } from '@/i18n';
import { useTheme } from '@/theme/useTheme';

// Первый вход: название магазина, часовой пояс, язык (docs/design.md, 12.3, шаг 3).
export default function ShopSetup() {
  const router = useRouter();
  const { t } = useI18n();
  const { colors, spacing } = useTheme();
  const { createShop, locale } = useSession();
  const [name, setName] = useState('');
  const [lang, setLang] = useState<'ru' | 'kk'>(locale);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    if (!name.trim()) {
      setError(t('shopSetup.name'));
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await createShop(name.trim(), 'Asia/Almaty', lang);
      router.replace('/');
    } catch (e) {
      setError(errorMessage(e, t('common.unknownError')));
    } finally {
      setBusy(false);
    }
  };

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: colors.bg }} edges={['bottom']}>
      <View style={{ flex: 1, padding: spacing.lg, gap: spacing.lg }}>
        <TextField
          label={t('shopSetup.name')}
          value={name}
          onChangeText={(v) => {
            setName(v);
            setError(null);
          }}
          placeholder={t('shopSetup.namePlaceholder')}
          autoCapitalize="sentences"
          error={error}
          maxLength={120}
        />
        <Card>
          <Txt variant="footnoteStrong" tone="secondary">{t('shopSetup.tz')}</Txt>
          <Txt variant="body" style={{ marginTop: 4 }}>{t('shopSetup.tzAlmaty')}</Txt>
        </Card>
        <View style={{ gap: spacing.sm }}>
          <Txt variant="footnoteStrong" tone="secondary">{t('shopSetup.language')}</Txt>
          <View style={{ flexDirection: 'row', gap: spacing.sm }}>
            {(['ru', 'kk'] as const).map((l) => (
              <Pressable
                key={l}
                accessibilityRole="radio"
                accessibilityState={{ selected: lang === l }}
                onPress={() => setLang(l)}
                style={{
                  flex: 1,
                  height: 44,
                  borderRadius: 12,
                  borderWidth: 1,
                  borderColor: lang === l ? colors.primary : colors.border,
                  backgroundColor: lang === l ? colors.primarySoft : colors.surface,
                  alignItems: 'center',
                  justifyContent: 'center',
                }}
              >
                <Txt variant="subheadMedium" tone={lang === l ? 'primaryText' : 'secondary'}>{l === 'ru' ? 'Русский' : 'Қазақша'}</Txt>
              </Pressable>
            ))}
          </View>
        </View>
        <View style={{ marginTop: 'auto' }}>
          <Button title={t('shopSetup.done')} onPress={submit} loading={busy} fullWidth />
        </View>
      </View>
    </SafeAreaView>
  );
}
