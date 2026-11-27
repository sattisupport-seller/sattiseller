import { listenForTaps } from '@/lib/push';
import {
  Inter_400Regular,
  Inter_500Medium,
  Inter_600SemiBold,
  Inter_700Bold,
  useFonts,
} from '@expo-google-fonts/inter';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { Stack, useRouter, useSegments } from 'expo-router';
import * as SplashScreen from 'expo-splash-screen';
import { StatusBar } from 'expo-status-bar';
import { useEffect } from 'react';
import { useAppConfig } from '@/api/hooks';
import { setAnalyticsEnabled } from '@/lib/analytics';
import { ActivityIndicator, View } from 'react-native';

// Нативный экран запуска (spec-2.1, раздел 15.2) держим, пока не загружены шрифты.
SplashScreen.preventAutoHideAsync().catch(() => {});

import { reportClientError, setAccountBlockedHandler, setAccountDeactivatedHandler, setSubscriptionRequiredHandler } from '@/api/client';
import { SessionProvider, useSession } from '@/session/SessionProvider';
import { ToastProvider } from '@/components/ui/Overlays';
import { useTheme } from '@/theme/useTheme';
import { useI18n } from '@/i18n';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: 2, staleTime: 60_000, refetchOnWindowFocus: true },
  },
});

export default function RootLayout() {
  // Необработанные ошибки приложения уходят на сервер (ТЗ 2.1, 14.4); стандартная реакция сохраняется.
  useEffect(() => {
    const previous = ErrorUtils.getGlobalHandler();
    ErrorUtils.setGlobalHandler((error, isFatal) => {
      reportClientError('global', String((error as Error)?.message ?? error));
      previous?.(error, isFatal);
    });
  }, []);
  const [fontsLoaded, fontError] = useFonts({
    Inter_400Regular,
    Inter_500Medium,
    Inter_600SemiBold,
    Inter_700Bold,
  });
  // Если шрифт не загрузился, интерфейс работает на системном шрифте (docs/design.md, 4.1).
  const ready = fontsLoaded || !!fontError;
  useEffect(() => {
    if (ready) SplashScreen.hideAsync().catch(() => {});
  }, [ready]);
  return (
    <QueryClientProvider client={queryClient}>
      <SessionProvider>
        <ToastProvider>
          {ready ? <Shell /> : <Splash />}
        </ToastProvider>
      </SessionProvider>
    </QueryClientProvider>
  );
}

function Splash() {
  const { colors } = useTheme();
  return (
    <View style={{ flex: 1, alignItems: 'center', justifyContent: 'center', backgroundColor: colors.bg }}>
      <ActivityIndicator color={colors.primary} />
    </View>
  );
}

function Shell() {
  const { colors, mode } = useTheme();
  const { status, termsRequired } = useSession();
  const appConfig = useAppConfig();
  // 3.9: отправка событий — только когда сервер включил флаг analytics
  useEffect(() => { setAnalyticsEnabled(appConfig.data?.flags.analytics ?? false); }, [appConfig.data?.flags.analytics]);
  const router = useRouter();
  const segments = useSegments();
  const { t } = useI18n();

  // Сервер ответил subscription_required — показываем экран блокировки (ТЗ 2.1, 9.2).
  useEffect(() => {
    setSubscriptionRequiredHandler(() => router.push('/subscription-ended'));
    setAccountBlockedHandler(() => router.replace('/account-blocked' as never));
    setAccountDeactivatedHandler(() => router.replace('/account-deactivated' as never));
  }, [router]);

  // 3.4: нажатие на уведомление — нужный экран (склад, обзор, товар)
  useEffect(() => listenForTaps((path) => router.push(path as never)), [router]);

  // Смена статуса сессии (вход, выход, истёкшая сессия) — переход на стартовый маршрут.
  useEffect(() => {
    if (status === 'loading') return;
    const first = segments[0] as string | undefined;
    if (status === 'signedOut' && first !== 'welcome' && first !== 'login' && first !== 'code') {
      router.replace('/welcome');
    }
    // 1.19: версия условий изменилась — до согласия остальные экраны недоступны.
    if (status !== 'signedOut' && termsRequired && first !== 'terms-consent') {
      router.replace('/terms-consent');
    }
  }, [status, termsRequired, router, segments]);

  return (
    <>
      <StatusBar style={mode === 'dark' ? 'light' : 'dark'} />
      <Stack
        screenOptions={{
          headerShown: false,
          contentStyle: { backgroundColor: colors.bg },
          headerStyle: { backgroundColor: colors.surface },
          headerTintColor: colors.primary,
          headerShadowVisible: false,
          headerTitleStyle: { color: colors.textPrimary },
        }}
      >
        <Stack.Screen name="index" options={{ headerShown: false }} />
        <Stack.Screen name="welcome" options={{ headerShown: false }} />
        <Stack.Screen name="login" options={{ headerShown: true, title: t('login.title'), headerBackTitle: t('common.back') }} />
        <Stack.Screen name="code" options={{ headerShown: true, title: t('code.title'), headerBackTitle: t('common.back') }} />
        <Stack.Screen name="shop-setup" options={{ headerShown: true, title: t('shopSetup.title'), headerBackVisible: false }} />
        <Stack.Screen name="update-required" options={{ headerShown: false }} />
        <Stack.Screen name="account-blocked" options={{ headerShown: false, gestureEnabled: false }} />
        <Stack.Screen name="account-deactivated" options={{ headerShown: false, gestureEnabled: false }} />
        <Stack.Screen name="terms-consent" options={{ headerShown: false, gestureEnabled: false }} />
        <Stack.Screen name="(tabs)" options={{ headerShown: false }} />
        <Stack.Screen name="profit" options={{ headerShown: true, title: t('profit.title'), headerBackTitle: t('common.back') }} />
        <Stack.Screen name="order/[id]" options={{ headerShown: true, title: t('orderDetail.title', { number: '' }), headerBackTitle: t('common.back') }} />
        <Stack.Screen name="product/[id]" options={{ headerShown: true, title: '', headerBackTitle: t('common.back') }} />
        <Stack.Screen name="product/cost/[id]" options={{ presentation: 'modal', headerShown: true, title: t('cost.title') }} />
        <Stack.Screen name="quick-cost" options={{ presentation: 'modal', headerShown: true, title: t('quickCost.title') }} />
        <Stack.Screen name="import" options={{ presentation: 'modal', headerShown: true, title: t('imp.title') }} />
        <Stack.Screen name="assistant/product-draft" options={{ headerShown: true, title: t('assistant.productDraftTitle'), headerBackTitle: t('common.back') }} />
        <Stack.Screen name="assistant/reply-draft" options={{ headerShown: true, title: t('assistant.replyTitle'), headerBackTitle: t('common.back') }} />
        <Stack.Screen name="settings/commissions" options={{ headerShown: true, title: t('settings.commissionsTitle'), headerBackTitle: t('common.back') }} />
        <Stack.Screen name="settings/expenses" options={{ headerShown: true, title: t('settings.expensesTitle'), headerBackTitle: t('common.back') }} />
        <Stack.Screen name="settings/notifications" options={{ headerShown: true, title: t('settings.notifTitle'), headerBackTitle: t('common.back') }} />
        <Stack.Screen name="settings/delete-account" options={{ headerShown: true, title: t('settings.deleteTitle'), headerBackTitle: t('common.back') }} />
        <Stack.Screen name="settings/how-profit" options={{ headerShown: true, title: t('settings.howTitle'), headerBackTitle: t('common.back') }} />
        <Stack.Screen name="settings/kaspi" options={{ headerShown: true, title: t('settings.kaspiTitle'), headerBackTitle: t('common.back') }} />
        <Stack.Screen name="catalog" options={{ headerShown: true, title: t('catalog.title'), headerBackTitle: t('common.back') }} />
      </Stack>
    </>
  );
}
