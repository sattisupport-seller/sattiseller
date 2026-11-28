// К-33 А4: отмена после передачи в Kaspi Доставку — «едет обратно», подтверждение «забрал»; буфер; подсказка о прайсе.
import { fireEvent, render, screen } from '@testing-library/react-native';

const mockPickedUp = jest.fn();

jest.mock('expo-haptics', () => ({ selectionAsync: jest.fn(() => Promise.resolve()) }));
jest.mock('expo-router', () => ({
  useRouter: () => ({ push: jest.fn(), back: jest.fn(), replace: jest.fn() }),
  useLocalSearchParams: () => ({}),
  Stack: { Screen: () => null },
}));
jest.mock('@/components/ui/Overlays', () => ({ ...jest.requireActual('@/components/ui/Overlays'), useToast: () => ({ show: jest.fn() }) }));
jest.mock('@/session/SessionProvider', () => ({ useSession: () => ({ shopId: 'shop-1', isDemo: false, locale: 'ru' }) }));
jest.mock('@/api/hooks', () => {
  const m = require('./screenMocks');
  return m.hooksMock({
    useShops: () => m.hookResult({ data: { items: [{ id: 'shop-1', name: 'М' }] } }),
    useStockList: () => m.hookResult({ data: { items: [{ productId: 'p1', sku: 'D007', name: 'Термокружка', current: 7,
      baseQty: 10, soldSince: 3, returnedSince: 0, avgDaily: 0, daysLeft: null, level: null, delisted: false,
      pendingReturns: 0, returning: 3, buffer: 2, forSale: 5 }] } }),
    useStockAlerts: () => m.hookResult({ data: { items: [], endingSoon: [] } }),
    useProducts: () => m.hookResult({ data: { pages: [{ items: [{ product_id: 'p1', sku: 'D007', name: 'Термокружка' }] }] } }),
    useStockMutations: () => ({
      receipt: m.hookResult(), inventory: m.hookResult(), delist: m.hookResult(), relist: m.hookResult(),
      confirmReturns: m.hookResult(), pickedUp: m.hookResult({ mutate: mockPickedUp }), buffer: m.hookResult(),
    }),
  });
});

const StockScreen = require('@/app/stock').default;

test('едет обратно: подтверждение «забрал», буфер и подсказка о прайсе Kaspi', async () => {
  await render(<StockScreen />);
  expect(screen.getByText(/Едет обратно: 3 шт\./)).toBeTruthy();
  expect(screen.getByText('Буфер 2 шт. — в Kaspi видно 5 шт.')).toBeTruthy();
  expect(screen.getByText(/примерно раз в час/)).toBeTruthy();
  await fireEvent.press(screen.getByRole('button', { name: 'Забрал — годен' }));
  expect(mockPickedUp).toHaveBeenCalledWith({ productId: 'p1', qty: 3, sellable: true });
  await fireEvent.press(screen.getByRole('button', { name: 'Забрал — брак' }));
  expect(mockPickedUp).toHaveBeenCalledWith({ productId: 'p1', qty: 3, sellable: false });
}, 60_000);
