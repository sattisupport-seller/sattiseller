import type { ReactNode } from 'react';
import { Pressable, View } from 'react-native';
import { useRouter } from 'expo-router';
import { ChevronLeft } from 'lucide-react-native';

import { useTheme } from '@/theme/useTheme';

import { Txt } from './Text';

// Шапка корневого экрана вкладки: title1 слева, строка subhead, до двух кнопок справа (docs/design.md, 10.19).
export function TabHeader({ title, subtitle, right }: { title: string; subtitle?: ReactNode; right?: ReactNode }) {
  const { spacing } = useTheme();
  return (
    <View style={{ flexDirection: 'row', alignItems: 'flex-start', justifyContent: 'space-between', paddingTop: spacing.md, paddingBottom: spacing.md }}>
      <View style={{ flex: 1, gap: 4 }}>
        <Txt variant="title1" accessibilityRole="header">{title}</Txt>
        {subtitle ? <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>{subtitle}</View> : null}
      </View>
      {right ? <View style={{ flexDirection: 'row', gap: 4 }}>{right}</View> : null}
    </View>
  );
}

/** Кнопка назад для модальных экранов, если системная шапка не используется. */
export function BackButton({ label }: { label: string }) {
  const router = useRouter();
  const { colors } = useTheme();
  return (
    <Pressable accessibilityRole="button" accessibilityLabel={label} onPress={() => router.back()} hitSlop={10} style={{ flexDirection: 'row', alignItems: 'center', gap: 2 }}>
      <ChevronLeft size={22} color={colors.primary} />
      <Txt variant="body" tone="primaryText">{label}</Txt>
    </Pressable>
  );
}
