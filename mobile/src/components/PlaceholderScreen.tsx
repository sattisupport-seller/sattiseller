import { SafeAreaView } from 'react-native-safe-area-context';
import { StyleSheet, Text, View } from 'react-native';

import { t } from '@/i18n';
import { useTheme } from '@/theme/useTheme';

type Props = { title: string };

// Заготовка экрана до его задачи в плане. Содержимое появится позже.
export function PlaceholderScreen({ title }: Props) {
  const theme = useTheme();
  const { colors, spacing, fonts } = theme;

  return (
    <SafeAreaView style={[styles.root, { backgroundColor: colors.bg }]} edges={['top']}>
      <View style={[styles.wrap, { padding: spacing.lg }]}>
        <Text style={{ color: colors.textPrimary, fontFamily: fonts.bold, fontSize: 28 }}>{title}</Text>
        <Text style={{ color: colors.textSecondary, fontFamily: fonts.regular, fontSize: 16, marginTop: spacing.md }}>
          {t.placeholder.soon}
        </Text>
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1 },
  wrap: { flex: 1 },
});
