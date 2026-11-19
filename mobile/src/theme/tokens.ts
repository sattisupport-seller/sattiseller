// Токены темы из docs/design.md, разделы 3–5. Значения не вписываются в компоненты напрямую.

export type ColorTokens = {
  bg: string;
  surface: string;
  surfaceAlt: string;
  border: string;
  divider: string;
  borderStrong: string;
  textPrimary: string;
  textSecondary: string;
  textTertiary: string;
  textDisabled: string;
  overlay: string;
  primary: string;
  primaryButton: string;
  primaryPressed: string;
  onPrimary: string;
  primarySoft: string;
  onPrimarySoft: string;
  success: string;
  successSoft: string;
  onSuccessSoft: string;
  danger: string;
  dangerSoft: string;
  onDangerSoft: string;
  warning: string;
  warningSoft: string;
  onWarningSoft: string;
  info: string;
  infoSoft: string;
  onInfoSoft: string;
};

export const lightColors: ColorTokens = {
  bg: '#F5F6FA',
  surface: '#FFFFFF',
  surfaceAlt: '#EEF0F5',
  border: '#E2E5EC',
  divider: '#ECEEF3',
  borderStrong: '#808797',
  textPrimary: '#121826',
  textSecondary: '#4A5162',
  textTertiary: '#646C7E',
  textDisabled: '#A3A9B6',
  overlay: 'rgba(16,24,40,0.40)',
  primary: '#4F46E5',
  primaryButton: '#4F46E5',
  primaryPressed: '#4338CA',
  onPrimary: '#FFFFFF',
  primarySoft: '#EEF0FF',
  onPrimarySoft: '#3730A3',
  success: '#15803D',
  successSoft: '#E7F6EC',
  onSuccessSoft: '#166534',
  danger: '#B91C1C',
  dangerSoft: '#FDECEC',
  onDangerSoft: '#991B1B',
  warning: '#B45309',
  warningSoft: '#FEF3C7',
  onWarningSoft: '#92400E',
  info: '#1D4ED8',
  infoSoft: '#E6EEFF',
  onInfoSoft: '#1E40AF',
};

export const darkColors: ColorTokens = {
  bg: '#0C0F16',
  surface: '#151A24',
  surfaceAlt: '#1D2330',
  border: '#2A3140',
  divider: '#222836',
  borderStrong: '#6B7386',
  textPrimary: '#F2F4F8',
  textSecondary: '#C0C6D2',
  textTertiary: '#9AA2B2',
  textDisabled: '#5B6375',
  overlay: 'rgba(0,0,0,0.60)',
  primary: '#8B93FF',
  primaryButton: '#5B5BF0',
  primaryPressed: '#4B4BD6',
  onPrimary: '#FFFFFF',
  primarySoft: '#23264D',
  onPrimarySoft: '#C7CBFF',
  success: '#4ADE80',
  successSoft: '#12301F',
  onSuccessSoft: '#86EFAC',
  danger: '#F87171',
  dangerSoft: '#3A1717',
  onDangerSoft: '#FCA5A5',
  warning: '#FBBF24',
  warningSoft: '#3A2A0B',
  onWarningSoft: '#FCD34D',
  info: '#7DA2FF',
  infoSoft: '#182644',
  onInfoSoft: '#BFD0FF',
};

// Шкала отступов (docs/design.md, 5.1)
export const spacing = {
  '2xs': 2,
  xs: 4,
  sm: 8,
  md: 12,
  lg: 16,
  xl: 20,
  '2xl': 24,
  '3xl': 32,
  '4xl': 40,
} as const;

// Радиусы (docs/design.md, 5.2)
export const radii = {
  xs: 6,
  sm: 10,
  md: 12,
  lg: 16,
  xl: 20,
  full: 9999,
} as const;

// Шрифт Inter (docs/design.md, 4.1). Имена — из @expo-google-fonts/inter.
export const fonts = {
  regular: 'Inter_400Regular',
  medium: 'Inter_500Medium',
  semibold: 'Inter_600SemiBold',
  bold: 'Inter_700Bold',
} as const;
