import * as Haptics from 'expo-haptics';
import type { ReactNode } from 'react';
import { ActivityIndicator, Pressable, StyleSheet, View, type ViewStyle } from 'react-native';

import { useTheme } from '@/theme/useTheme';

import { Txt } from './Text';

export type ButtonVariant = 'primary' | 'secondary' | 'outline' | 'text' | 'destructive' | 'destructiveText';
export type ButtonSize = 'L' | 'M' | 'S';

type Props = {
  title: string;
  onPress: () => void;
  variant?: ButtonVariant;
  size?: ButtonSize;
  icon?: ReactNode;
  loading?: boolean;
  disabled?: boolean;
  fullWidth?: boolean;
  style?: ViewStyle;
  accessibilityHint?: string;
};

// Кнопки из docs/design.md, раздел 10.1: высота L 52, M 44, S 36.
const HEIGHT: Record<ButtonSize, number> = { L: 52, M: 44, S: 36 };
const RADIUS: Record<ButtonSize, number> = { L: 12, M: 12, S: 10 };
const PADDING_X: Record<ButtonSize, number> = { L: 20, M: 16, S: 12 };

export function Button({
  title, onPress, variant = 'primary', size = 'L', icon, loading, disabled, fullWidth, style, accessibilityHint,
}: Props) {
  const { colors, spacing } = useTheme();
  const isDisabled = disabled || loading;

  const palette = paletteFor(variant, colors);
  const bg = isDisabled && variant !== 'text' && variant !== 'destructiveText' ? colors.surfaceAlt : palette.bg;
  const fg = isDisabled ? colors.textDisabled : palette.fg;
  const border = variant === 'outline' ? { borderWidth: 1, borderColor: isDisabled ? colors.border : colors.borderStrong } : null;

  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={title}
      accessibilityHint={accessibilityHint}
      accessibilityState={{ disabled: !!isDisabled, busy: !!loading }}
      disabled={isDisabled}
      hitSlop={6}
      onPress={() => {
        Haptics.selectionAsync().catch(() => undefined);
        onPress();
      }}
      style={({ pressed }) => [
        styles.base,
        {
          height: HEIGHT[size],
          borderRadius: RADIUS[size],
          paddingHorizontal: PADDING_X[size],
          backgroundColor: pressed && !isDisabled ? pressedBg(variant, colors) : bg,
          alignSelf: fullWidth ? 'stretch' : 'flex-start',
        },
        border,
        style,
      ]}
    >
      <View style={[styles.row, { gap: spacing.sm }]}>
        {loading ? <ActivityIndicator color={fg} /> : icon}
        <Txt variant={size === 'S' ? 'buttonS' : 'buttonL'} style={{ color: fg }} numeric={false}>
          {title}
        </Txt>
      </View>
    </Pressable>
  );
}

function paletteFor(variant: ButtonVariant, c: ReturnType<typeof useTheme>['colors']) {
  switch (variant) {
    case 'primary':
      return { bg: c.primaryButton, fg: c.onPrimary };
    case 'secondary':
      return { bg: c.primarySoft, fg: c.onPrimarySoft };
    case 'outline':
      return { bg: 'transparent', fg: c.textPrimary };
    case 'text':
      return { bg: 'transparent', fg: c.primary };
    case 'destructive':
      return { bg: c.danger, fg: '#FFFFFF' };
    case 'destructiveText':
      return { bg: 'transparent', fg: c.danger };
  }
}

function pressedBg(variant: ButtonVariant, c: ReturnType<typeof useTheme>['colors']) {
  switch (variant) {
    case 'primary':
      return c.primaryPressed;
    case 'secondary':
      return c.primarySoft;
    case 'outline':
    case 'text':
    case 'destructiveText':
      return c.surfaceAlt;
    case 'destructive':
      return c.danger;
  }
}

const styles = StyleSheet.create({
  base: { justifyContent: 'center', minWidth: 44 },
  row: { flexDirection: 'row', alignItems: 'center', justifyContent: 'center' },
});
