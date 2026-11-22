// Код склада Kaspi (К-7, 22.11): без кода — предупреждение; подсказка из заказов подставляется по нажатию;
// неверный код не отправляется; верный уходит PUT-запросом.
import { fireEvent, render, screen, waitFor } from '@testing-library/react-native';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

const mockPut = jest.fn(async (..._a: unknown[]) => ({ store_ids: ['PP1'] }));

jest.mock('expo-haptics', () => ({ selectionAsync: jest.fn(() => Promise.resolve()) }));
jest.mock('expo-router', () => ({
  useRouter: () => ({ push: jest.fn(), back: jest.fn(), replace: jest.fn() }),
  useLocalSearchParams: () => ({}),
  Stack: { Screen: () => null },
}));
jest.mock('expo-linking', () => ({ openURL: jest.fn(), createURL: (p: string) => p }));
jest.mock('expo-clipboard', () => ({ setStringAsync: jest.fn(async () => true) }));
jest.mock('@/components/ui/Overlays', () => ({ ...jest.requireActual('@/components/ui/Overlays'), useToast: () => ({ show: jest.fn() }) }));
jest.mock('@/session/SessionProvider', () => ({ useSession: () => ({ shopId: 'shop-1', isDemo: false, locale: 'ru' }) }));
jest.mock('@/api/client', () => ({
  request: jest.fn(async (path: string, opts?: { method?: string; body?: unknown }) => {
    if (opts?.method === 'PUT' && path.includes('/kaspi/stores')) return mockPut(opts.body);
    return { enabled: true, status: 'active', seller_id: 'S-1', last_sync_at: null, last_error: null,
             price_url: 'https://x.example/price/1', store_ids: [], store_hint: 'PP1' };
  }),
  ApiError: class extends Error { code = ''; status = 0; },
}));
jest.mock('@/api/hooks', () => require('./screenMocks').hooksMock({
  useAppConfig: () => require('./screenMocks').hookResult({ data: { flags: { kaspi_connection: true } } }),
}));

const KaspiScreen = require('@/app/settings/kaspi').default;

function renderScreen() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}><KaspiScreen /></QueryClientProvider>);
}

beforeEach(() => mockPut.mockClear());

test('без кода склада показывается предупреждение об остатках', async () => {
  await renderScreen();
  expect(await screen.findByText('Остатки не передаются в Kaspi — укажите код склада')).toBeTruthy();
});

test('подсказка из заказов подставляется в поле, и код сохраняется', async () => {
  await renderScreen();
  await fireEvent.press(await screen.findByRole('button', { name: 'Использовать PP1' }));
  await fireEvent.press(screen.getByRole('button', { name: 'Сохранить код склада' }));
  await waitFor(() => expect(mockPut).toHaveBeenCalledWith({ store_ids: ['PP1'] }));
});

test('неверный код склада не отправляется и подсказывает правило', async () => {
  await renderScreen();
  await fireEvent.changeText(await screen.findByLabelText('Код склада (storeId)'), 'склад 1');
  await fireEvent.press(screen.getByRole('button', { name: 'Сохранить код склада' }));
  expect(mockPut).not.toHaveBeenCalled();
  expect(await screen.findByText('Код склада: латиница, цифры, «-» и «_», до 40 знаков')).toBeTruthy();
});
