import { Tabs } from 'expo-router';
import { CircleUser, LayoutDashboard, Package, Receipt, Sparkles } from 'lucide-react-native';

import { t } from '@/i18n';
import { useTheme } from '@/theme/useTheme';

// Пять вкладок по docs/design.md, раздел 10.18: Обзор, Заказы, Товары, Помощник, Профиль.
export default function TabsLayout() {
  const theme = useTheme();
  const { colors } = theme;

  return (
    <Tabs
      screenOptions={{
        headerShown: false,
        tabBarActiveTintColor: colors.primary,
        tabBarInactiveTintColor: colors.textTertiary,
        tabBarStyle: { backgroundColor: colors.surface, borderTopColor: colors.divider },
        tabBarLabelStyle: { fontFamily: theme.fonts.medium, fontSize: 11 },
      }}
    >
      <Tabs.Screen
        name="index"
        options={{
          title: t.tabs.overview,
          tabBarIcon: ({ color }) => <LayoutDashboard color={color} size={24} />,
        }}
      />
      <Tabs.Screen
        name="orders"
        options={{
          title: t.tabs.orders,
          tabBarIcon: ({ color }) => <Receipt color={color} size={24} />,
        }}
      />
      <Tabs.Screen
        name="products"
        options={{
          title: t.tabs.products,
          tabBarIcon: ({ color }) => <Package color={color} size={24} />,
        }}
      />
      <Tabs.Screen
        name="assistant"
        options={{
          title: t.tabs.assistant,
          tabBarIcon: ({ color }) => <Sparkles color={color} size={24} />,
        }}
      />
      <Tabs.Screen
        name="profile"
        options={{
          title: t.tabs.profile,
          tabBarIcon: ({ color }) => <CircleUser color={color} size={24} />,
        }}
      />
    </Tabs>
  );
}
