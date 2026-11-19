import { Linking, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Download } from 'lucide-react-native';

import { Button } from '@/components/ui/Button';
import { Txt } from '@/components/ui/Text';
import { useI18n } from '@/i18n';
import { useTheme } from '@/theme/useTheme';

// Экран «Обновите приложение» (docs/spec.md, раздел 4.6 и 12.24).
export default function UpdateRequired() {
  const { t } = useI18n();
  const { colors, spacing } = useTheme();
  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: colors.bg }}>
      <View style={{ flex: 1, alignItems: 'center', justifyContent: 'center', padding: spacing.lg, gap: spacing.lg }}>
        <View style={{ width: 72, height: 72, borderRadius: 36, backgroundColor: colors.primarySoft, alignItems: 'center', justifyContent: 'center' }}>
          <Download size={32} color={colors.onPrimarySoft} />
        </View>
        <Txt variant="title2" align="center">{t('update.title')}</Txt>
        <Txt variant="body" tone="secondary" align="center">{t('update.body')}</Txt>
        <Button title={t('update.button')} onPress={() => Linking.openURL('https://apps.apple.com/')} fullWidth />
      </View>
    </SafeAreaView>
  );
}
