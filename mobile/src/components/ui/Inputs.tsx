import { Search, X, CircleAlert, Eye, EyeOff } from 'lucide-react-native';
import { useState, type ReactNode } from 'react';
import { Pressable, StyleSheet, TextInput, View, type KeyboardTypeOptions } from 'react-native';

import { useTheme } from '@/theme/useTheme';

import { Txt } from './Text';

type FieldProps = {
  label?: string;
  value: string;
  onChangeText: (v: string) => void;
  placeholder?: string;
  error?: string | null;
  hint?: string;
  keyboardType?: KeyboardTypeOptions;
  autoCapitalize?: 'none' | 'sentences';
  suffix?: string;
  secure?: boolean;
  accessibilityLabel?: string;
  autoFocus?: boolean;
  maxLength?: number;
  returnKeyType?: 'done' | 'next' | 'search';
  onSubmitEditing?: () => void;
  multiline?: boolean;
  minHeight?: number;
  testID?: string;
};

// Поля ввода: высота 52, радиус 12, рамка 1 pt; фокус — рамка 2 pt primary; ошибка — danger (docs/design.md, 10.3).
export function TextField({
  label, value, onChangeText, placeholder, error, hint, keyboardType, autoCapitalize = 'none', suffix,
  secure, accessibilityLabel, autoFocus, maxLength, returnKeyType, onSubmitEditing, multiline, minHeight, testID,
}: FieldProps) {
  const { colors, spacing, radii, fonts } = useTheme();
  const [focused, setFocused] = useState(false);
  const [revealed, setRevealed] = useState(false);
  const borderColor = error ? colors.danger : focused ? colors.primary : colors.borderStrong;
  const borderWidth = error || focused ? 2 : 1;

  return (
    <View style={{ gap: 6 }}>
      {label ? <Txt variant="subheadMedium" tone="secondary">{label}</Txt> : null}
      <View
        style={[
          styles.field,
          {
            backgroundColor: colors.surface,
            borderColor,
            borderWidth,
            borderRadius: radii.md,
            paddingHorizontal: spacing.lg,
            minHeight: multiline ? minHeight ?? 96 : 52,
            alignItems: multiline ? 'flex-start' : 'center',
            paddingVertical: multiline ? spacing.md : 0,
          },
        ]}
      >
        <TextInput
          testID={testID}
          accessibilityLabel={accessibilityLabel ?? label ?? placeholder}
          value={value}
          onChangeText={onChangeText}
          placeholder={placeholder}
          placeholderTextColor={colors.textTertiary}
          keyboardType={keyboardType}
          autoCapitalize={autoCapitalize}
          autoCorrect={false}
          autoFocus={autoFocus}
          secureTextEntry={secure && !revealed}
          maxLength={maxLength}
          returnKeyType={returnKeyType}
          onSubmitEditing={onSubmitEditing}
          multiline={multiline}
          onFocus={() => setFocused(true)}
          onBlur={() => setFocused(false)}
          style={[
            styles.input,
            { color: colors.textPrimary, fontFamily: fonts.regular, textAlignVertical: multiline ? 'top' : 'center' },
            multiline ? { minHeight: 80, width: '100%' } : null,
          ]}
        />
        {suffix ? <Txt variant="body" tone="tertiary">{suffix}</Txt> : null}
        {secure ? (
          <Pressable
            accessibilityRole="button"
            accessibilityLabel={revealed ? 'Скрыть' : 'Показать'}
            onPress={() => setRevealed((r) => !r)}
            hitSlop={10}
            style={{ paddingLeft: spacing.sm }}
          >
            {revealed ? <EyeOff size={20} color={colors.textTertiary} /> : <Eye size={20} color={colors.textTertiary} />}
          </Pressable>
        ) : null}
      </View>
      {error ? (
        <View style={styles.row}>
          <CircleAlert size={16} color={colors.danger} />
          <Txt variant="footnote" tone="danger" style={{ flex: 1 }}>{error}</Txt>
        </View>
      ) : hint ? (
        <Txt variant="footnote" tone="tertiary">{hint}</Txt>
      ) : null}
    </View>
  );
}

/** Денежное поле: цифровая клавиатура, суффикс ₸ справа. Сумма уходит на сервер строкой. */
export function MoneyField(props: Omit<FieldProps, 'keyboardType' | 'suffix'>) {
  return <TextField {...props} keyboardType="decimal-pad" suffix="₸" />;
}

type SearchProps = {
  value: string;
  onChangeText: (v: string) => void;
  placeholder: string;
};

// Поиск: высота 44, фон surfaceAlt, без рамки (docs/design.md, 10.4).
export function SearchField({ value, onChangeText, placeholder }: SearchProps) {
  const { colors, radii, spacing, fonts } = useTheme();
  return (
    <View style={[styles.search, { backgroundColor: colors.surfaceAlt, borderRadius: radii.md, paddingHorizontal: spacing.md }]}>
      <Search size={20} color={colors.textTertiary} />
      <TextInput
        accessibilityLabel={placeholder}
        value={value}
        onChangeText={onChangeText}
        placeholder={placeholder}
        placeholderTextColor={colors.textTertiary}
        autoCapitalize="none"
        autoCorrect={false}
        returnKeyType="search"
        style={[styles.input, { color: colors.textPrimary, fontFamily: fonts.regular, marginLeft: spacing.sm }]}
      />
      {value ? (
        <Pressable accessibilityRole="button" accessibilityLabel="Очистить" onPress={() => onChangeText('')} hitSlop={10}>
          <X size={18} color={colors.textTertiary} />
        </Pressable>
      ) : null}
    </View>
  );
}

type SegmentedProps<T extends string> = {
  value: T | null;
  options: { value: T; label: string }[];
  onChange: (v: T) => void;
  accessibilityLabel?: string;
};

// Переключатель периода и вида (docs/design.md, 10.5): высота 36, радиус 10, выбранный сегмент — surface.
export function Segmented<T extends string>({ value, options, onChange, accessibilityLabel }: SegmentedProps<T>) {
  const { colors, radii, fonts } = useTheme();
  return (
    <View
      accessibilityRole="tablist"
      accessibilityLabel={accessibilityLabel}
      style={[styles.segmented, { backgroundColor: colors.surfaceAlt, borderRadius: radii.sm }]}
    >
      {options.map((o) => {
        const selected = o.value === value;
        return (
          <Pressable
            key={o.value}
            accessibilityRole="tab"
            accessibilityState={{ selected }}
            accessibilityLabel={o.label}
            onPress={() => onChange(o.value)}
            style={[
              styles.segment,
              {
                backgroundColor: selected ? colors.surface : 'transparent',
                borderRadius: radii.sm - 2,
                shadowColor: '#101828',
                shadowOpacity: selected && colors.bg !== '#0C0F16' ? 0.08 : 0,
                shadowRadius: 2,
                shadowOffset: { width: 0, height: 1 },
                elevation: selected ? 1 : 0,
              },
            ]}
          >
            <Txt variant="subhead" tone={selected ? 'primary' : 'secondary'} style={{ fontFamily: selected ? fonts.semibold : fonts.medium }}>
              {o.label}
            </Txt>
          </Pressable>
        );
      })}
    </View>
  );
}

export function Row({ children }: { children: ReactNode }) {
  return <View style={styles.row}>{children}</View>;
}

const styles = StyleSheet.create({
  field: { flexDirection: 'row', flex: 0 },
  input: { flex: 1, fontSize: 16, paddingVertical: 0 },
  row: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  search: { height: 44, flexDirection: 'row', alignItems: 'center' },
  segmented: { flexDirection: 'row', padding: 2, height: 36 },
  segment: { flex: 1, alignItems: 'center', justifyContent: 'center', height: 32, minWidth: 44 },
});
