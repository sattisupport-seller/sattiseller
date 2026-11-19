import { ChevronRight, CircleCheck, Info, TriangleAlert } from 'lucide-react-native';
import type { ReactNode } from 'react';
import { Pressable, StyleSheet, View, type ViewStyle } from 'react-native';

import { useTheme } from '@/theme/useTheme';

import { Txt } from './Text';

// Карточка: surface, радиус 16, рамка 1 pt (в тёмной теме без рамки), отступ 16 (docs/design.md, 10.8).
export function Card({ children, style, onPress, accessibilityLabel }: {
  children: ReactNode; style?: ViewStyle; onPress?: () => void; accessibilityLabel?: string;
}) {
  const { colors, radii, spacing, mode } = useTheme();
  const body = (
    <View
      style={[
        {
          backgroundColor: colors.surface,
          borderRadius: radii.lg,
          padding: spacing.lg,
          borderWidth: mode === 'dark' ? 0 : 1,
          borderColor: colors.border,
        },
        style,
      ]}
    >
      {children}
    </View>
  );
  if (!onPress) return body;
  return (
    <Pressable accessibilityRole="button" accessibilityLabel={accessibilityLabel} onPress={onPress}
      style={({ pressed }) => ({ opacity: pressed ? 0.92 : 1 })}>
      {body}
    </Pressable>
  );
}

export type Tone = 'success' | 'danger' | 'warning' | 'info' | 'neutral' | 'primary' | 'outline';

const TONE_STYLE: Record<Tone, { bg: (c: ReturnType<typeof useTheme>['colors']) => string; fg: (c: ReturnType<typeof useTheme>['colors']) => string; border?: boolean }> = {
  success: { bg: (c) => c.successSoft, fg: (c) => c.onSuccessSoft },
  danger: { bg: (c) => c.dangerSoft, fg: (c) => c.onDangerSoft },
  warning: { bg: (c) => c.warningSoft, fg: (c) => c.onWarningSoft },
  info: { bg: (c) => c.infoSoft, fg: (c) => c.onInfoSoft },
  neutral: { bg: (c) => c.surfaceAlt, fg: (c) => c.textSecondary },
  primary: { bg: (c) => c.primarySoft, fg: (c) => c.onPrimarySoft },
  outline: { bg: () => 'transparent', fg: (c) => c.textSecondary, border: true },
};

// Бейдж: высота 22, радиус 6, поля 8, caption SemiBold (docs/design.md, 10.7).
export function Badge({ label, tone = 'neutral', icon }: { label: string; tone?: Tone; icon?: ReactNode }) {
  const { colors, radii, spacing } = useTheme();
  const t = TONE_STYLE[tone];
  return (
    <View
      accessible
      accessibilityLabel={label}
      style={{
        height: 22,
        paddingHorizontal: spacing.sm,
        borderRadius: radii.xs,
        backgroundColor: t.bg(colors),
        borderWidth: t.border ? 1 : 0,
        borderColor: colors.borderStrong,
        flexDirection: 'row',
        alignItems: 'center',
        gap: 4,
        alignSelf: 'flex-start',
      }}
    >
      {icon}
      <Txt variant="captionStrong" style={{ color: t.fg(colors) }}>{label}</Txt>
    </View>
  );
}

// Чип-фильтр: высота 32, радиус full, поля 12 (docs/design.md, 10.6).
export function Chip({ label, selected, onPress, count }: { label: string; selected: boolean; onPress: () => void; count?: number }) {
  const { colors, spacing } = useTheme();
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityState={{ selected }}
      accessibilityLabel={count !== undefined ? `${label}, ${count}` : label}
      onPress={onPress}
      style={{
        height: 32,
        paddingHorizontal: 12,
        borderRadius: 9999,
        borderWidth: 1,
        borderColor: selected ? colors.primary : colors.border,
        backgroundColor: selected ? colors.primarySoft : colors.surface,
        justifyContent: 'center',
        marginRight: spacing.sm,
      }}
    >
      <Txt variant="subheadMedium" tone={selected ? 'primaryText' : 'secondary'}>
        {count !== undefined ? `${label} ${count}` : label}
      </Txt>
    </Pressable>
  );
}

// Баннер: радиус 12, отступ 12, иконка 20 (docs/design.md, 10.10).
export function Banner({ text, tone = 'info', action, onAction }: {
  text: string; tone?: 'info' | 'warning' | 'danger' | 'neutral' | 'primary'; action?: string; onAction?: () => void;
}) {
  const { colors, radii, spacing } = useTheme();
  const map = {
    info: { bg: colors.infoSoft, fg: colors.onInfoSoft, Icon: Info },
    primary: { bg: colors.primarySoft, fg: colors.onPrimarySoft, Icon: Info },
    warning: { bg: colors.warningSoft, fg: colors.onWarningSoft, Icon: TriangleAlert },
    danger: { bg: colors.dangerSoft, fg: colors.onDangerSoft, Icon: TriangleAlert },
    neutral: { bg: colors.surfaceAlt, fg: colors.textSecondary, Icon: Info },
  }[tone];
  return (
    <View
      accessibilityRole="alert"
      style={[styles.banner, { backgroundColor: map.bg, borderRadius: radii.md, padding: spacing.md }]}
    >
      <map.Icon size={20} color={map.fg} />
      <Txt variant="subhead" style={{ color: map.fg, flex: 1 }}>{text}</Txt>
      {action && onAction ? (
        <Pressable accessibilityRole="button" onPress={onAction} hitSlop={8}>
          <Txt variant="buttonS" style={{ color: map.fg }}>{action}</Txt>
        </Pressable>
      ) : null}
    </View>
  );
}

// Секция: footnoteStrong, отступы сверху 24 и снизу 8 (docs/design.md, 10.9).
export function Section({ title, action, onAction, children }: {
  title: string; action?: string; onAction?: () => void; children?: ReactNode;
}) {
  const { colors, spacing } = useTheme();
  return (
    <View style={{ marginTop: spacing['2xl'], gap: spacing.sm }}>
      <View style={styles.between}>
        <Txt variant="footnoteStrong" tone="secondary" accessibilityRole="header">{title}</Txt>
        {action && onAction ? (
          <Pressable accessibilityRole="button" onPress={onAction} hitSlop={8}>
            <Txt variant="buttonS" style={{ color: colors.primary }}>{action}</Txt>
          </Pressable>
        ) : null}
      </View>
      {children}
    </View>
  );
}

// Полоса покрытия: высота 8, дорожка surfaceAlt; цвет по порогам (docs/design.md, 10.11).
export function CoverageBar({ bp }: { bp: number }) {
  const { colors, radii } = useTheme();
  const color = bp >= 9500 ? colors.success : bp >= 7000 ? colors.warning : colors.danger;
  const pct = Math.max(0, Math.min(100, bp / 100));
  return (
    <View
      accessibilityRole="progressbar"
      accessibilityValue={{ min: 0, max: 100, now: Math.round(pct) }}
      accessibilityLabel={`Покрытие ${Math.round(pct)}%`}
      style={{ height: 8, borderRadius: radii.full, backgroundColor: colors.surfaceAlt, overflow: 'hidden' }}
    >
      <View style={{ width: `${pct}%`, height: 8, backgroundColor: color, borderRadius: radii.full }} />
    </View>
  );
}

// Строка списка: минимальная высота 56, вертикальные отступы 12 (docs/design.md, 10.9).
export function ListRow({ title, subtitle, right, badges, onPress, accessibilityLabel, last }: {
  title: string;
  subtitle?: string;
  right?: ReactNode;
  badges?: ReactNode;
  onPress?: () => void;
  accessibilityLabel?: string;
  last?: boolean;
}) {
  const { colors, spacing } = useTheme();
  const body = (
    <View style={[styles.rowWrap, { paddingVertical: spacing.md, paddingHorizontal: spacing.lg, minHeight: 56 }]}>
      <View style={{ flex: 1, gap: 4 }}>
        <Txt variant="bodyMedium" numberOfLines={2}>{title}</Txt>
        {subtitle ? <Txt variant="subhead" tone="tertiary" numberOfLines={1}>{subtitle}</Txt> : null}
        {badges}
      </View>
      {right}
      {onPress ? <ChevronRight size={16} color={colors.textTertiary} /> : null}
    </View>
  );
  return (
    <View>
      {onPress ? (
        <Pressable
          accessibilityRole="button"
          accessibilityLabel={accessibilityLabel ?? title}
          onPress={onPress}
          style={({ pressed }) => ({ backgroundColor: pressed ? colors.surfaceAlt : 'transparent' })}
        >
          {body}
        </Pressable>
      ) : (
        body
      )}
      {!last ? <View style={{ height: StyleSheet.hairlineWidth, backgroundColor: colors.divider, marginLeft: spacing.lg }} /> : null}
    </View>
  );
}

// Список сгруппированный в карточку с внутренними разделителями.
export function GroupCard({ children }: { children: ReactNode }) {
  const { colors, radii } = useTheme();
  return <View style={{ backgroundColor: colors.surface, borderRadius: radii.lg, borderWidth: 1, borderColor: colors.border, overflow: 'hidden' }}>{children}</View>;
}

export function Stepper({ step, total }: { step: number; total: number }) {
  const { colors, radii, spacing } = useTheme();
  return (
    <View style={{ flexDirection: 'row', gap: spacing.xs }}>
      {Array.from({ length: total }).map((_, i) => (
        <View
          key={i}
          style={{ flex: 1, height: 4, borderRadius: radii.full, backgroundColor: i < step ? colors.primary : colors.surfaceAlt }}
        />
      ))}
    </View>
  );
}

export function SuccessMark() {
  const { colors } = useTheme();
  return <CircleCheck size={32} color={colors.success} />;
}

const styles = StyleSheet.create({
  banner: { flexDirection: 'row', alignItems: 'center', gap: 10 },
  between: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  rowWrap: { flexDirection: 'row', alignItems: 'center', gap: 12 },
});
