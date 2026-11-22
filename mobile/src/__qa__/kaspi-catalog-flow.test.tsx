// Прайс продавца (К-16.3, 22.11): без загруженного прайса ссылку не показываем, объясняем; кнопка загрузки есть.
import { render, screen } from '@testing-library/react-native';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

jest.mock('expo-haptics', () => ({ selectionAsync: jest.fn(() => Promise.resolve()) }));
jest.mock('expo-router', () => ({
  useRouter: () => ({ push: jest.fn(), back: jest.fn(), replace: jest.fn() }),
  useLocalSearchParams: () => ({}),
  Stack: { Screen: () => null },
}));
jest.mock('expo-linking', () => ({ openURL: jest.fn(), createURL: (p: string) => p }));
jest.mock('expo-clipboard', () => ({ setStringAsync: jest.fn(async () => true) }));
jest.mock('expo-document-picker', () => ({ getDocumentAsync: jest.fn(async () => ({ canceled: true, assets: [] })) }));
jest.mock('@/components/ui/Overlays', () => ({ ...jest.requireActual('@/components/ui/Overlays'), useToast: () => ({ show: jest.fn() }) }));
jest.mock('@/session/SessionProvider', () => ({ useSession: () => ({ shopId: 'shop-1', isDemo: false, locale: 'ru' }) }));
jest.mock('@/api/client', () => ({
  request: jest.fn(async () => ({
    enabled: true, status: 'active', seller_id: 'S-1', last_sync_at: null, last_error: null,
    price_url: null, store_ids: [], store_hint: null, catalog: null,
    price_hint: 'Сначала загрузите прайс-лист из кабинета Kaspi',
  })),
  ApiError: class extends Error { code = ''; status = 0; },
}));
jest.mock('@/api/hooks', () => require('./screenMocks').hooksMock({
  useAppConfig: () => require('./screenMocks').hookResult({ data: { flags: { kaspi_connection: true } } }),
}));

const KaspiScreen = require('@/app/settings/kaspi').default;

test('без прайса: объяснение вместо ссылки, кнопка загрузки есть', async () => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  await render(<QueryClientProvider client={qc}><KaspiScreen /></QueryClientProvider>);
  expect(await screen.findByText('Сначала загрузите прайс-лист из кабинета Kaspi')).toBeTruthy();
  expect(screen.queryByText('Адрес прайс-листа для кабинета Kaspi')).toBeNull();
  expect(screen.getByRole('button', { name: 'Загрузить прайс-лист (XML)' })).toBeTruthy();
});
