// QA-10: каждый экран рисуется без данных и с данными, на русском и казахском, в светлой и тёмной теме.
import { render } from '@testing-library/react-native';

import AssistantScreen from '@/app/(tabs)/assistant';
import OverviewScreen from '@/app/(tabs)/index';
import OrdersScreen from '@/app/(tabs)/orders';
import ProductsScreen from '@/app/(tabs)/products';
import ProfileScreen from '@/app/(tabs)/profile';
import ProductDraftScreen from '@/app/assistant/product-draft';
import ReplyDraftScreen from '@/app/assistant/reply-draft';
import CatalogScreen from '@/app/catalog';
import CodeScreen from '@/app/code';
import ImportScreen from '@/app/import';
import IndexScreen from '@/app/index';
import LoginScreen from '@/app/login';
import OrderDetailScreen from '@/app/order/[id]';
import PaywallScreen from '@/app/paywall';
import ProductDetailScreen from '@/app/product/[id]';
import ProductCostScreen from '@/app/product/cost/[id]';
import ProfitScreen from '@/app/profit';
import QuickCostScreen from '@/app/quick-cost';
import CommissionsScreen from '@/app/settings/commissions';
import DeleteAccountScreen from '@/app/settings/delete-account';
import ExpensesScreen from '@/app/settings/expenses';
import HowProfitScreen from '@/app/settings/how-profit';
import KaspiScreen from '@/app/settings/kaspi';
import NotificationsScreen from '@/app/settings/notifications';
import TaxScreen from '@/app/settings/tax';
import ShopSetupScreen from '@/app/shop-setup';
import SubscriptionEndedScreen from '@/app/subscription-ended';
import UpdateRequiredScreen from '@/app/update-required';
import WelcomeScreen from '@/app/welcome';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

import { ToastProvider } from '@/components/ui/Overlays';

const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });

let mockLocale: 'ru' | 'kk' = 'ru';
let mockTheme: 'light' | 'dark' = 'light';
let mockData = false;  // false — пустые ответы API, true — фикстуры (демо-данные, сняты с сервера)

jest.mock('expo-router', () => ({
  useRouter: () => ({ push: jest.fn(), back: jest.fn(), replace: jest.fn(), navigate: jest.fn(), canGoBack: () => false }),
  useLocalSearchParams: () => ({ id: 'p1', productId: 'p1' }),
  useFocusEffect: () => undefined,
  useNavigation: () => ({ setOptions: jest.fn(), addListener: () => () => undefined }),
  Link: ({ children }: { children: unknown }) => children,
  Stack: Object.assign(() => null, { Screen: () => null }),
  Tabs: Object.assign(() => null, { Screen: () => null }),
  Redirect: () => null,
  router: { push: jest.fn(), back: jest.fn(), replace: jest.fn() },
}));

jest.mock('@/session/SessionProvider', () => ({
  useSession: () => ({
    shopId: 'shop-1', isDemo: true, shops: [{ id: 'shop-1', name: 'Демо-магазин', timezone: 'Asia/Almaty', language: 'ru' }],
    user: { id: 'u1', email: 'seller@example.invalid', name: 'Продавец', locale: mockLocale, ageConfirmed: true },
    locale: mockLocale, setLocale: jest.fn(), themeMode: mockTheme, setThemeMode: jest.fn(),
    signedIn: true, signOut: jest.fn(), refreshSession: jest.fn(), setShopId: jest.fn(),
  }),
  SessionProvider: ({ children }: { children: unknown }) => children,
}));

// Данные API: пустые ответы (пустые состояния) или фикстуры с демо-данными (заполненные состояния)
jest.mock('@/api/hooks', () => {
  const fixtures: Record<string, unknown> = {
    appConfig: require('./fixtures/appConfig.json'), shops: require('./fixtures/shops.json'),
    overview: require('./fixtures/overview.json'), profit: require('./fixtures/profit.json'),
    orders: require('./fixtures/orders.json'), orderDetail: require('./fixtures/orderDetail.json'),
    products: require('./fixtures/products.json'), productDetail: require('./fixtures/productDetail.json'),
    missingCosts: require('./fixtures/missingCosts.json'), costVersions: require('./fixtures/costVersions.json'),
    commissions: require('./fixtures/commissions.json'), tax: require('./fixtures/tax.json'),
    expenses: require('./fixtures/expenses.json'), aiQuota: require('./fixtures/aiQuota.json'),
    subscription: require('./fixtures/subscription.json'),
  };
  const byHook: Record<string, string> = {
    useAppConfig: 'appConfig', useShops: 'shops', useOverview: 'overview', useProfitBreakdown: 'profit',
    useOrders: 'orders', useOrder: 'orderDetail', useProducts: 'products', useProduct: 'productDetail',
    useMissingCosts: 'missingCosts', useCostVersions: 'costVersions', useCommissions: 'commissions', useTax: 'tax',
    useExpenses: 'expenses', useAIQuota: 'aiQuota', useSubscription: 'subscription',
  };
  return new Proxy({}, {
    get: (_target, name: string) => () => {
      const key = byHook[name];
      const raw = mockData && key ? fixtures[key] : undefined;
      // бесконечные списки (useOrders, useProducts) отдают данные в формате { pages: [...] }, как в хуках приложения
      const infinite = name === 'useOrders' || name === 'useProducts';
      const data = infinite && raw !== undefined ? { pages: [raw], pageParams: [undefined] } : raw;
      return {
        data, isLoading: false, isError: false, isFetching: false, error: null,
        hasNextPage: false, fetchNextPage: jest.fn(), isFetchingNextPage: false,
        refetch: jest.fn(), mutateAsync: jest.fn(async () => ({})), mutate: jest.fn(), isPending: false,
      };
    },
  });
});

const screens: Array<[string, () => JSX.Element]> = [
  ['обзор', OverviewScreen], ['заказы', OrdersScreen], ['товары', ProductsScreen], ['профиль', ProfileScreen],
  ['помощник', AssistantScreen], ['черновик товара', ProductDraftScreen], ['ответ покупателю', ReplyDraftScreen],
  ['каталог', CatalogScreen], ['код', CodeScreen], ['импорт', ImportScreen], ['старт', IndexScreen],
  ['вход', LoginScreen], ['заказ', OrderDetailScreen], ['подписка', PaywallScreen], ['товар', ProductDetailScreen],
  ['себестоимость', ProductCostScreen], ['прибыль', ProfitScreen], ['быстрая себестоимость', QuickCostScreen],
  ['комиссии', CommissionsScreen], ['удаление аккаунта', DeleteAccountScreen], ['расходы', ExpensesScreen],
  ['как считается прибыль', HowProfitScreen], ['Kaspi', KaspiScreen], ['уведомления', NotificationsScreen],
  ['налог', TaxScreen], ['настройка магазина', ShopSetupScreen], ['подписка закончилась', SubscriptionEndedScreen],
  ['нужно обновить', UpdateRequiredScreen], ['приветствие', WelcomeScreen],
] as Array<[string, () => JSX.Element]>;

describe.each([
  ['ru', 'light', false], ['ru', 'light', true], ['kk', 'dark', true],
] as const)('экраны (%s, %s, данные: %s)', (locale, theme, withData) => {
  beforeAll(() => {
    mockLocale = locale;
    mockTheme = theme;
    mockData = withData;
  });
  test.each(screens)('%s рисуется', (_name, Screen) => {
    // проверка: экран рисуется без исключений (очистка после теста — автоматическая, RNTL 14)
    render(<QueryClientProvider client={queryClient}><ToastProvider><Screen /></ToastProvider></QueryClientProvider>);
  });
});
