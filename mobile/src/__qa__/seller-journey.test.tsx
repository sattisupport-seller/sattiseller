// К-30 п.2 (jest): путь нового продавца по экранам приложения на одном поддельном сервере —
// без галочки нет входа → пока обучение не пройдено, Kaspi закрыт → после обучения форма Kaspi с предупреждением
// «токен один раз» → себестоимость и остаток вместе → возврат подтверждается на складе.
import { fireEvent, render, screen, waitFor } from '@testing-library/react-native';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { Alert } from 'react-native';

const mockServer = {
  onboardingDone: false,
  kaspi: 'not_connected' as 'not_connected' | 'active',
  costs: {} as Record<string, unknown>,
  calls: [] as { path: string; body?: unknown }[],
};
const mockStart = jest.fn();

jest.mock('expo-haptics', () => ({ selectionAsync: jest.fn(() => Promise.resolve()) }));
jest.mock('expo-router', () => ({ useRouter: () => ({ push: jest.fn(), back: jest.fn(), replace: jest.fn() }), useLocalSearchParams: () => ({}), Stack: { Screen: () => null } }));
jest.mock('@/components/ui/Overlays', () => ({ ...jest.requireActual('@/components/ui/Overlays'), useToast: () => ({ show: jest.fn() }) }));
jest.mock('@/session/SessionProvider', () => ({ useSession: () => ({ shopId: 'shop-1', isDemo: false, locale: 'ru', status: 'ready', email: null }) }));
jest.mock('@/onboarding/OnboardingProvider', () => ({ useTour: () => ({ active: false, index: 0, done: mockServer.onboardingDone, start: mockStart }) }));
jest.mock('@/api/client', () => ({
  ApiError: class extends Error {},
  request: jest.fn(async (path: string, opts?: { method?: string; body?: unknown }) => {
    mockServer.calls.push({ path, body: opts?.body });
    if (path.endsWith('/kaspi/connection') && opts?.method === 'POST') { mockServer.kaspi = 'active'; return { enabled: true, status: 'active' }; }
    if (path.endsWith('/kaspi/connection')) return { enabled: true, status: mockServer.kaspi, seller_id: 'S-1', last_sync_at: null };
    return {};
  }),
}));
const mockBulk = jest.fn(async (body: unknown) => { mockServer.calls.push({ path: 'bulk', body }); return { saved: 1 }; });
const mockConfirm = jest.fn();
jest.mock('@/api/hooks', () => {
  const m = require('./screenMocks');
  return m.hooksMock({
    useAppConfig: () => m.hookResult({ data: { flags: { kaspi_connection: true }, privacy_url: 'p', terms_url: 't' } }),
    useMissingCosts: () => m.hookResult({ data: { items: [
      { product_id: 'p1', sku: 'K0', name: 'Кружка', needs_cost: true, needs_stock: true, stock_hint: 4 }] } }),
    useBulkCost: () => m.hookResult({ mutateAsync: mockBulk }),
    useStockList: () => m.hookResult({ data: { items: [{ productId: 'p1', sku: 'K0', name: 'Кружка', current: 1, baseQty: 4,
      soldSince: 3, returnedSince: 0, avgDaily: 0, daysLeft: null, level: 't3', delisted: false, pendingReturns: 3 }] } }),
    useStockAlerts: () => m.hookResult({ data: { items: [], endingSoon: [] } }),
    useProducts: () => m.hookResult({ data: { pages: [{ items: [{ product_id: 'p1', sku: 'K0', name: 'Кружка' }] }] } }),
    useStockMutations: () => ({ receipt: m.hookResult(), inventory: m.hookResult(), delist: m.hookResult(), relist: m.hookResult(),
      confirmReturns: m.hookResult({ mutate: mockConfirm }) }),
  });
});

const KaspiScreen = require('@/app/settings/kaspi').default;
const QuickCostScreen = require('@/app/quick-cost').default;
const StockScreen = require('@/app/stock').default;

function withQuery(node: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{node}</QueryClientProvider>;
}

// Шаги идут по порядку и меняют общее состояние поддельного сервера (jest выполняет тесты файла последовательно).
test('1. обучение не пройдено — подключение Kaspi закрыто', async () => {
  await render(withQuery(<KaspiScreen />));
  expect(await screen.findByText(/Сначала пройдите обучение/)).toBeTruthy();
  expect(screen.queryByLabelText('ID продавца')).toBeNull();
});

test('2. после обучения — форма Kaspi и предупреждение «токен один раз»', async () => {
  mockServer.onboardingDone = true;
  const alert = jest.spyOn(Alert, 'alert').mockImplementation((...args: unknown[]) => {
    (args[2] as { text: string; onPress?: () => void }[]).find((b) => b.text === 'Понятно, подключить')?.onPress?.();
  });
  await render(withQuery(<KaspiScreen />));
  await fireEvent.changeText(await screen.findByLabelText('ID продавца'), 'S-1');
  await fireEvent.changeText(screen.getByLabelText('Ключ доступа (токен)'), 'token-0123456789');
  await fireEvent.press(screen.getByRole('button', { name: 'Подключить магазин' }));
  await waitFor(() => expect(alert).toHaveBeenCalled());
  expect(alert.mock.calls[0][1]).toContain('только один раз');
  await waitFor(() => expect(mockServer.calls.some((c) => c.path.endsWith('/kaspi/connection') && c.body)).toBe(true));
  alert.mockRestore();
});

test('3. себестоимость и остаток вместе; остаток из прайса подставлен', async () => {
  await render(withQuery(<QuickCostScreen />));
  expect(screen.getByLabelText('Кружка: Остаток сейчас, шт.').props.value).toBe('4');
  await fireEvent.changeText(screen.getByLabelText('Кружка: Закупка'), '2000');
  await fireEvent.press(screen.getByRole('button', { name: /^Сохранить/ }));
  await waitFor(() => expect(mockBulk).toHaveBeenCalledWith({
    items: [{ product_id: 'p1', purchase: '2000', stock_qty: 4 }], apply_to_history: true }));
});

test('4. возврат подтверждается на складе', async () => {
  await render(<StockScreen />);
  expect(screen.getByText(/Подтвердите возврат на склад: 3 шт\./)).toBeTruthy();
  await fireEvent.press(screen.getByRole('button', { name: 'Вернулся на склад' }));
  expect(mockConfirm).toHaveBeenCalledWith({ productId: 'p1', sellable: true });
});
