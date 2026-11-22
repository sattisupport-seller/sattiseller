import { useRouter } from 'expo-router';
import { useState } from 'react';
import { View, Pressable } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { Button } from '@/components/ui/Button';
import { TextField } from '@/components/ui/Inputs';
import { Txt } from '@/components/ui/Text';
import { Card } from '@/components/ui/Surfaces';
import { request } from '@/api/client';
import { errorMessage, useSession } from '@/session/SessionProvider';
import { useI18n } from '@/i18n';
import { useTheme } from '@/theme/useTheme';

// Первый вход: название магазина, часовой пояс, язык (docs/design.md, 12.3, шаг 3).
export default function ShopSetup() {
  const router = useRouter();
  const { t } = useI18n();
  const { colors, spacing } = useTheme();
  const { createShop } = useSession();
  const [name, setName] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [age, setAge] = useState(false);
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    if (!name.trim()) {
      setError(t('shopSetup.name'));
      return;
    }
    if (!age) {
      setError(t('shopSetup.ageRequired'));
      return;
    }
    setBusy(true);
    setError(null);
    try {
      // Возраст 18+ фиксируется на сервере до создания магазина (ADR-0004).
      await request('/me/age-confirm', { method: 'POST' });
      await createShop(name.trim(), 'Asia/Almaty', 'ru');
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
        <Pressable
          accessibilityRole="checkbox"
          accessibilityState={{ checked: age }}
          accessibilityLabel={t('shopSetup.ageLabel')}
          onPress={() => {
            setAge((v) => !v);
            setError(null);
          }}
          style={{ flexDirection: 'row', alignItems: 'center', gap: spacing.md, minHeight: 44 }}
        >
          <View
            style={{
              width: 24,
              height: 24,
              borderRadius: 6,
              borderWidth: 2,
              borderColor: age ? colors.primary : colors.borderStrong,
              backgroundColor: age ? colors.primary : colors.surface,
            }}
          />
          <Txt variant="body" style={{ flex: 1 }}>{t('shopSetup.ageLabel')}</Txt>
        </Pressable>
        <View style={{ marginTop: 'auto' }}>
          <Button title={t('shopSetup.done')} onPress={submit} loading={busy} fullWidth />
        </View>
      </View>
    </SafeAreaView>
  );
}
