import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { AccessibilityInfo, Animated, Modal, Pressable, RefreshControl, SafeAreaView, ScrollView, StyleSheet, View, type ViewStyle } from 'react-native';
import { CircleAlert, Inbox } from 'lucide-react-native';

import { useTheme } from '@/theme/useTheme';

import { Button } from './Button';
import { Txt } from './Text';

// Лист снизу: верхние углы 20, ручка 36×4, затемнение overlay (docs/design.md, 10.12).
export function Sheet({ visible, onClose, title, children }: {
  visible: boolean; onClose: () => void; title?: string; children: ReactNode;
}) {
  const { colors, radii, spacing } = useTheme();
  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={onClose}>
      <View style={[StyleSheet.absoluteFill, { backgroundColor: colors.overlay }]}>
        <Pressable accessibilityLabel="Закрыть" accessibilityRole="button" style={{ flex: 1 }} onPress={onClose} />
        <SafeAreaView style={[styles.sheet, { backgroundColor: colors.surface, borderTopLeftRadius: 20, borderTopRightRadius: 20, maxHeight: '90%' }]}>
          <View style={{ alignItems: 'center', paddingTop: 8 }}>
            <View style={{ width: 36, height: 4, borderRadius: radii.full, backgroundColor: colors.textDisabled }} />
          </View>
          {title ? (
            <Txt variant="title3" style={{ paddingHorizontal: spacing.lg, paddingTop: spacing.md }} accessibilityRole="header">{title}</Txt>
          ) : null}
          <ScrollView keyboardShouldPersistTaps="handled" contentContainerStyle={{ padding: spacing.lg, gap: spacing.md }}>
            {children}
          </ScrollView>
        </SafeAreaView>
      </View>
    </Modal>
  );
}

// Тост над панелью вкладок: инверсия, исчезает через 4 с, с действием — через 8 с (docs/design.md, 10.14).
type ToastState = { id: number; text: string; action?: { label: string; onPress: () => void } } | null;
type ToastCtx = { show: (text: string, action?: { label: string; onPress: () => void }) => void };
const ToastContext = createContext<ToastCtx | null>(null);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toast, setToast] = useState<ToastState>(null);
  const opacity = useRef(new Animated.Value(0)).current;
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const show = useCallback((text: string, action?: { label: string; onPress: () => void }) => {
    if (timer.current) clearTimeout(timer.current);
    setToast({ id: Date.now(), text, action });
    Animated.timing(opacity, { toValue: 1, duration: 150, useNativeDriver: true }).start();
    timer.current = setTimeout(() => {
      Animated.timing(opacity, { toValue: 0, duration: 150, useNativeDriver: true }).start(() => setToast(null));
    }, action ? 8000 : 4000);
  }, [opacity]);

  const value = useMemo(() => ({ show }), [show]);
  return (
    <ToastContext.Provider value={value}>
      {children}
      {toast ? <ToastView toast={toast} opacity={opacity} /> : null}
    </ToastContext.Provider>
  );
}

function ToastView({ toast, opacity }: { toast: NonNullable<ToastState>; opacity: Animated.Value }) {
  const { colors, radii, spacing } = useTheme();
  return (
    <Animated.View
      pointerEvents="box-none"
      style={[styles.toastWrap, { opacity }]}
    >
      <View
        accessibilityLiveRegion="polite"
        style={{
          backgroundColor: colors.textPrimary,
          borderRadius: radii.md,
          padding: spacing.md,
          flexDirection: 'row',
          alignItems: 'center',
          gap: spacing.md,
        }}
      >
        <Txt variant="subhead" style={{ color: colors.bg, flex: 1 }}>{toast.text}</Txt>
        {toast.action ? (
          <Pressable accessibilityRole="button" onPress={toast.action.onPress} hitSlop={8}>
            <Txt variant="buttonS" style={{ color: colors.primary }}>{toast.action.label}</Txt>
          </Pressable>
        ) : null}
      </View>
    </Animated.View>
  );
}

export function useToast(): ToastCtx {
  const v = useContext(ToastContext);
  if (!v) throw new Error('useToast вне ToastProvider');
  return v;
}

// Пустое состояние: иконка 32 в круге 72 primarySoft, заголовок title3, текст subhead (docs/design.md, 10.16).
export function EmptyState({ title, body, action, onAction }: { title: string; body?: string; action?: string; onAction?: () => void }) {
  const { colors, spacing } = useTheme();
  return (
    <View style={{ alignItems: 'center', paddingVertical: spacing['3xl'], gap: spacing.md, paddingHorizontal: spacing.lg }}>
      <View style={{ width: 72, height: 72, borderRadius: 36, backgroundColor: colors.primarySoft, alignItems: 'center', justifyContent: 'center' }}>
        <Inbox size={32} color={colors.onPrimarySoft} />
      </View>
      <Txt variant="title3" align="center">{title}</Txt>
      {body ? <Txt variant="subhead" tone="secondary" align="center">{body}</Txt> : null}
      {action && onAction ? <Button title={action} onPress={onAction} size="M" variant="primary" /> : null}
    </View>
  );
}

// Ошибка: круг dangerSoft, код ошибки footnote (docs/design.md, 10.16).
export function ErrorState({ title, body, code, onRetry }: { title: string; body?: string; code?: string; onRetry?: () => void }) {
  const { colors, spacing } = useTheme();
  return (
    <View style={{ alignItems: 'center', paddingVertical: spacing['3xl'], gap: spacing.md, paddingHorizontal: spacing.lg }}>
      <View style={{ width: 72, height: 72, borderRadius: 36, backgroundColor: colors.dangerSoft, alignItems: 'center', justifyContent: 'center' }}>
        <CircleAlert size={32} color={colors.onDangerSoft} />
      </View>
      <Txt variant="title3" align="center">{title}</Txt>
      {body ? <Txt variant="subhead" tone="secondary" align="center">{body}</Txt> : null}
      {code ? <Txt variant="footnote" tone="tertiary">Код: {code}</Txt> : null}
      {onRetry ? <Button title="Повторить" onPress={onRetry} size="M" /> : null}
    </View>
  );
}

// Скелетон: серые блоки surfaceAlt с мерцанием; при «Уменьшении движения» — без мерцания.
export function Skeleton({ height = 16, width = '100%', radius }: { height?: number; width?: number | string; radius?: number }) {
  const { colors, radii } = useTheme();
  const opacity = useRef(new Animated.Value(0.5)).current;
  const [reduce, setReduce] = useState(false);
  useEffect(() => {
    AccessibilityInfo.isReduceMotionEnabled().then(setReduce).catch(() => undefined);
    if (reduce) return;
    const loop = Animated.loop(
      Animated.sequence([
        Animated.timing(opacity, { toValue: 1, duration: 600, useNativeDriver: true }),
        Animated.timing(opacity, { toValue: 0.5, duration: 600, useNativeDriver: true }),
      ]),
    );
    loop.start();
    return () => loop.stop();
  }, [opacity, reduce]);
  return (
    <Animated.View
      accessibilityLabel="Загрузка"
      style={{ height, width: width as ViewStyle['width'], borderRadius: radius ?? radii.sm, backgroundColor: colors.surfaceAlt, opacity: reduce ? 1 : opacity }}
    />
  );
}

// Экран со скроллом и обновлением потягиванием (docs/spec.md, раздел 4.2).
export function ScreenScroll({ children, refreshing, onRefresh, padBottom = 120 }: {
  children: ReactNode; refreshing?: boolean; onRefresh?: () => void; padBottom?: number;
}) {
  const { colors, spacing } = useTheme();
  return (
    <ScrollView
      contentContainerStyle={{ paddingHorizontal: spacing.lg, paddingBottom: padBottom, paddingTop: spacing.sm }}
      refreshControl={onRefresh ? <RefreshControl refreshing={!!refreshing} onRefresh={onRefresh} tintColor={colors.primary} /> : undefined}
      showsVerticalScrollIndicator={false}
    >
      {children}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  sheet: { width: '100%', paddingBottom: 16 },
  toastWrap: { position: 'absolute', left: 16, right: 16, bottom: 96 },
});
