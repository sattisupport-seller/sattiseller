import { useColorScheme } from 'react-native';

import { useSession } from '@/session/SessionProvider';

import { ColorTokens, darkColors, fonts, lightColors, radii, spacing } from './tokens';

export type Theme = {
  mode: 'light' | 'dark';
  colors: ColorTokens;
  spacing: typeof spacing;
  radii: typeof radii;
  fonts: typeof fonts;
};

/** Тема: режим из профиля (как в системе / светлая / тёмная). */
export function useTheme(): Theme {
  const system = useColorScheme();
  const { themeMode } = useSession();
  const resolved = themeMode === 'system' ? (system === 'dark' ? 'dark' : 'light') : themeMode;
  return {
    mode: resolved,
    colors: resolved === 'dark' ? darkColors : lightColors,
    spacing,
    radii,
    fonts,
  };
}
