import { useColorScheme } from 'react-native';

import { ColorTokens, darkColors, lightColors, radii, spacing, fonts } from './tokens';

export type ThemeMode = 'system' | 'light' | 'dark';

export type Theme = {
  mode: 'light' | 'dark';
  colors: ColorTokens;
  spacing: typeof spacing;
  radii: typeof radii;
  fonts: typeof fonts;
};

// Пока тема берётся из системы. Ручной выбор (профиль, раздел 3.7 ТЗ) добавится позже.
export function useTheme(mode: ThemeMode = 'system'): Theme {
  const system = useColorScheme();
  const resolved = mode === 'system' ? (system === 'dark' ? 'dark' : 'light') : mode;
  return {
    mode: resolved,
    colors: resolved === 'dark' ? darkColors : lightColors,
    spacing,
    radii,
    fonts,
  };
}
