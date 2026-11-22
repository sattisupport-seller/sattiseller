// Дымовая отрисовка экранов (1.11, 22.11): каждый экран рендерится с общими моками API и без падения.
// Проверяет, что код экрана выполняется при обычных данных; глубокие сценарии — в отдельных тестах.
import { render } from '@testing-library/react-native';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import React from 'react';
import S0 from '@/app/catalog';
import S1 from '@/app/code';
import S2 from '@/app/settings/commissions';
import S3 from '@/app/settings/delete-account';
import S4 from '@/app/settings/expenses';
import S5 from '@/app/settings/how-profit';
import S6 from '@/app/settings/kaspi';
import S7 from '@/app/settings/notifications';
import S8 from '@/app/settings/tax';
import S9 from '@/app/import';
import S10 from '@/app/login';
import S11 from '@/app/paywall';
import S12 from '@/app/profit';
import S13 from '@/app/quick-cost';
import S14 from '@/app/shop-setup';
import S15 from '@/app/stock';
import S16 from '@/app/subscription-ended';
import S17 from '@/app/terms-consent';
import S18 from '@/app/update-required';
import S19 from '@/app/welcome';
import S20 from '@/app/assistant/product-draft';
import S21 from '@/app/assistant/reply-draft';
import S22 from '@/app/order/[id]';
import S23 from '@/app/product/[id]';
import S24 from '@/app/product/cost/[id]';

jest.mock('expo-haptics', () => ({ selectionAsync: jest.fn(() => Promise.resolve()) }));
jest.mock('expo-router', () => ({
  useRouter: () => ({ push: jest.fn(), back: jest.fn(), replace: jest.fn(), canGoBack: () => true }),
  useLocalSearchParams: () => ({ id: 'p1', tree: 'x' }),
  useGlobalSearchParams: () => ({}),
  useFocusEffect: jest.fn(),
  useNavigation: () => ({ setOptions: jest.fn(), addListener: () => () => undefined }),
  Stack: { Screen: () => null },
  Link: ({ children }: { children: React.ReactNode }) => children,
  Redirect: () => null,
}));
jest.mock('expo-file-system', () => ({ File: jest.fn(), Paths: { cache: '/tmp' } }));
jest.mock('expo-sharing', () => ({ shareAsync: jest.fn(), isAvailableAsync: jest.fn(async () => false) }));
jest.mock('expo-document-picker', () => ({ getDocumentAsync: jest.fn(async () => ({ canceled: true })) }));
jest.mock('expo-image-picker', () => ({ launchImageLibraryAsync: jest.fn(async () => ({ canceled: true })), requestMediaLibraryPermissionsAsync: jest.fn(async () => ({ granted: false })) }));
jest.mock('expo-linking', () => ({ openURL: jest.fn(), createURL: (p: string) => p }));
jest.mock('expo-web-browser', () => ({ openBrowserAsync: jest.fn(), maybeCompleteAuthSession: jest.fn() }));
jest.mock('@/components/ui/Overlays', () => ({ ...jest.requireActual('@/components/ui/Overlays'), useToast: () => ({ show: jest.fn() }) }));
jest.mock('@/session/SessionProvider', () => ({
  useSession: () => ({ shopId: 'shop-1', isDemo: true, locale: 'ru', signOut: jest.fn(), user: { email: 'a@example.invalid' }, requestCode: jest.fn(), signInWithIdToken: jest.fn(), acceptTerms: jest.fn() }),
}));
jest.mock('@/api/hooks', () => {
  const m = require('./screenMocks');
  return m.hooksMock({
    useStockMutations: () => ({ receipt: m.hookResult(), inventory: m.hookResult(), delist: m.hookResult(), relist: m.hookResult() }),
    useStockList: () => m.hookResult({ data: { items: [] } }),
    useStockAlerts: () => m.hookResult({ data: { items: [], endingSoon: [] } }),
  });
});

const SCREENS: [string, React.ComponentType][] = [
  ['catalog', S0],
  ['code', S1],
  ['commissions', S2],
  ['delete-account', S3],
  ['expenses', S4],
  ['how-profit', S5],
  ['kaspi', S6],
  ['notifications', S7],
  ['tax', S8],
  ['import', S9],
  ['login', S10],
  ['paywall', S11],
  ['profit', S12],
  ['quick-cost', S13],
  ['shop-setup', S14],
  ['stock', S15],
  ['subscription-ended', S16],
  ['terms-consent', S17],
  ['update-required', S18],
  ['welcome', S19],
  ['product-draft', S20],
  ['reply-draft', S21],
  ['order', S22],
  ['product', S23],
  ['product-cost', S24],
];

describe.each(SCREENS)('экран %s отрисовывается', (_name, Screen) => {
  test('без падения при обычных данных', async () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const tree = await render(<QueryClientProvider client={qc}><Screen /></QueryClientProvider>);
    expect(tree.toJSON()).toBeTruthy();
  });
});
