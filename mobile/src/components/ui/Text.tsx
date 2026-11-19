import { Text as RNText, type StyleProp, type TextProps, type TextStyle } from 'react-native';

import { useTheme } from '@/theme/useTheme';

// Стили текста из docs/design.md, раздел 4.2.
export const typography = {
  display: { size: 32, line: 38, weight: 'bold', tracking: -0.5 },
  title1: { size: 28, line: 34, weight: 'bold', tracking: -0.3 },
  title2: { size: 22, line: 28, weight: 'semibold', tracking: -0.2 },
  title3: { size: 18, line: 24, weight: 'semibold', tracking: 0 },
  kpi: { size: 26, line: 32, weight: 'semibold', tracking: -0.3 },
  headline: { size: 16, line: 22, weight: 'semibold', tracking: 0 },
  body: { size: 16, line: 22, weight: 'regular', tracking: 0 },
  bodyMedium: { size: 16, line: 22, weight: 'medium', tracking: 0 },
  subhead: { size: 14, line: 20, weight: 'regular', tracking: 0 },
  subheadMedium: { size: 14, line: 20, weight: 'medium', tracking: 0 },
  footnote: { size: 13, line: 18, weight: 'regular', tracking: 0 },
  footnoteStrong: { size: 13, line: 18, weight: 'semibold', tracking: 0 },
  caption: { size: 12, line: 16, weight: 'medium', tracking: 0 },
  captionStrong: { size: 12, line: 16, weight: 'semibold', tracking: 0 },
  tabLabel: { size: 11, line: 14, weight: 'medium', tracking: 0 },
  buttonL: { size: 16, line: 20, weight: 'semibold', tracking: 0 },
  buttonS: { size: 14, line: 18, weight: 'semibold', tracking: 0 },
} as const;

export type TextVariant = keyof typeof typography;
export type TextTone = 'primary' | 'secondary' | 'tertiary' | 'disabled' | 'success' | 'danger' | 'warning' | 'info' | 'onPrimary' | 'primaryText';

type Props = TextProps & {
  variant?: TextVariant;
  tone?: TextTone;
  align?: TextStyle['textAlign'];
  numeric?: boolean;
  style?: StyleProp<TextStyle>;
};

export function Txt({ variant = 'body', tone = 'primary', align, numeric, style, ...rest }: Props) {
  const { colors, fonts } = useTheme();
  const v = typography[variant];
  const color = toneColor(tone, colors);
  const family = weightFamily(v.weight, fonts);
  return (
    <RNText
      {...rest}
      style={[
        {
          fontSize: v.size,
          lineHeight: v.line,
          letterSpacing: v.tracking,
          fontFamily: family,
          color,
          textAlign: align,
          fontVariant: numeric ? ['tabular-nums'] : undefined,
        },
        style,
      ]}
    />
  );
}

function weightFamily(weight: string, fonts: { regular: string; medium: string; semibold: string; bold: string }) {
  switch (weight) {
    case 'bold':
      return fonts.bold;
    case 'semibold':
      return fonts.semibold;
    case 'medium':
      return fonts.medium;
    default:
      return fonts.regular;
  }
}

function toneColor(tone: TextTone, c: ReturnType<typeof useTheme>['colors']): string {
  switch (tone) {
    case 'secondary':
      return c.textSecondary;
    case 'tertiary':
      return c.textTertiary;
    case 'disabled':
      return c.textDisabled;
    case 'success':
      return c.success;
    case 'danger':
      return c.danger;
    case 'warning':
      return c.warning;
    case 'info':
      return c.info;
    case 'onPrimary':
      return c.onPrimary;
    case 'primaryText':
      return c.primary;
    default:
      return c.textPrimary;
  }
}
