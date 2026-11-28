// К-33 А3: режим презентации — пометка «пример» у остатка и предпросмотр автоснятия (в Kaspi ничего не меняется).
import { render, screen } from '@testing-library/react-native';

jest.mock('expo-haptics', () => ({ selectionAsync: jest.fn(() => Promise.resolve()) }));
jest.mock('expo-router', () => ({
  useRouter: () => ({ push: jest.fn(), back: jest.fn(), replace: jest.fn() }),
  useLocalSearchParams: () => ({}),
  Stack: { Screen: () => null },
}));
jest.mock('@/components/ui/Overlays', () => ({ ...jest.requireActual('@/components/ui/Overlays'), useToast: () => ({ show: jest.fn() }) }));
jest.mock('@/session/SessionProvider', () => ({ useSession: () => ({ shopId: 'shop-1', isDemo: false, locale: 'ru' }) }));

const row = (productId: string, name: string, current: number, example: boolean) => ({
  productId, sku: productId, name, current, baseQty: current, soldSince: 0, returnedSince: 0, avgDaily: 1,
  daysLeft: null, level: current <= 0 ? 'out' : null, delisted: false, pendingReturns: 0, example,
});

jest.mock('@/api/hooks', () => {
  const m = require('./screenMocks');
  return m.hooksMock({
    useShops: () => m.hookResult({ data: { items: [{ id: 'shop-1', name: 'М', presentation_mode: true, example_cost_pct: 60 }] } }),
    useStockList: () => m.hookResult({ data: { items: [row('p1', 'Термокружка', 0, true), row('p2', 'Чайник', 25, true)] } }),
    useStockAlerts: () => m.hookResult({ data: { items: [], endingSoon: [] } }),
    useProducts: () => m.hookResult({ data: { pages: [{ items: [
      { product_id: 'p1', sku: 'p1', name: 'Термокружка' }, { product_id: 'p2', sku: 'p2', name: 'Чайник' }] }] } }),
    useStockMutations: () => ({
      receipt: m.hookResult(), inventory: m.hookResult(), delist: m.hookResult(), relist: m.hookResult(), confirmReturns: m.hookResult(),
    }),
  });
});

const StockScreen = require('@/app/stock').default;

test('режим презентации: предпросмотр автоснятия и пометка «пример»', async () => {
  await render(<StockScreen />);
  expect(screen.getByText('Предпросмотр автоснятия: сейчас сняли бы 1')).toBeTruthy();
  expect(screen.getByText('Термокружка · 0 шт.')).toBeTruthy();
  expect(screen.getByText(/в магазине Kaspi ничего не меняется/)).toBeTruthy();
  expect(screen.getByText('25 шт. · пример')).toBeTruthy();
}, 60_000);
