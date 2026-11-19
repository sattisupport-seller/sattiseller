import type { ReactNode } from 'react';
import { Pressable } from 'react-native';

import { useTheme } from '@/theme/useTheme';

// Кнопка-иконка: зона 44×44, при нажатии круг surfaceAlt, подпись обязательна для VoiceOver (docs/design.md, 10.2).
export function IconButton({ label, onPress, children }: { label: string; onPress: () => void; children: ReactNode }) {
  const { colors } = useTheme();
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={label}
      onPress={onPress}
      hitSlop={4}
      style={({ pressed }) => ({
        width: 44,
        height: 44,
        borderRadius: 22,
        alignItems: 'center',
        justifyContent: 'center',
        backgroundColor: pressed ? colors.surfaceAlt : 'transparent',
      })}
    >
      {children}
    </Pressable>
  );
}
