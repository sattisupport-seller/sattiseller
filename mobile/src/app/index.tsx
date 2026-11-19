import Constants from 'expo-constants';
import { Redirect } from 'expo-router';
import { ActivityIndicator, Platform, View } from 'react-native';

import { useAppConfig } from '@/api/hooks';
import { useSession } from '@/session/SessionProvider';
import { useTheme } from '@/theme/useTheme';
import { isBelow } from '@/lib/version';

// Стартовый маршрут: проверка версии, техработ и статуса сессии.
export default function Index() {
  const { status } = useSession();
  const { colors } = useTheme();
  const { data: config, isLoading, isError } = useAppConfig();

  if (isLoading && !isError) {
    return (
      <View style={{ flex: 1, alignItems: 'center', justifyContent: 'center', backgroundColor: colors.bg }}>
        <ActivityIndicator color={colors.primary} />
      </View>
    );
  }

  if (config && isBelow(currentVersion(), minFor(config))) {
    return <Redirect href="/update-required" />;
  }

  if (status === 'loading') {
    return (
      <View style={{ flex: 1, alignItems: 'center', justifyContent: 'center', backgroundColor: colors.bg }}>
        <ActivityIndicator color={colors.primary} />
      </View>
    );
  }
  if (status === 'signedOut') return <Redirect href="/welcome" />;
  if (status === 'needsShop') return <Redirect href="/shop-setup" />;
  return <Redirect href="/(tabs)" />;
}

function currentVersion(): string {
  return (Constants.expoConfig?.version as string | undefined) ?? '1.0.0';
}

function minFor(config: { min_supported_version_ios: string; min_supported_version_android: string }): string {
  return Platform.OS === 'ios' ? config.min_supported_version_ios : config.min_supported_version_android;
}
