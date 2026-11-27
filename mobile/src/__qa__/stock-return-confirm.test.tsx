// К-26: возврат без отметки «вернулся на склад» — подсказка «Подтвердите возврат на склад» и кнопки подтверждения.
import { fireEvent, render, screen } from '@testing-library/react-native';

const mockConfirm = jest.fn();

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
    useStockList: () => m.hookResult({ data: { items: [{ productId: 'p1', sku: 'D007', name: 'Термокружка', current: 7,
      baseQty: 10, soldSince: 3, returnedSince: 0, avgDaily: 0, daysLeft: null, level: 't10', delisted: false, pendingReturns: 2 }] } }),
    useStockAlerts: () => m.hookResult({ data: { items: [], endingSoon: [] } }),
    useProducts: () => m.hookResult({ data: { pages: [{ items: [{ product_id: 'p1', sku: 'D007', name: 'Термокружка' }] }] } }),
    useStockMutations: () => ({
      receipt: m.hookResult(), inventory: m.hookResult(), delist: m.hookResult(), relist: m.hookResult(),
      confirmReturns: m.hookResult({ mutate: mockConfirm }),
    }),
  });
});

const StockScreen = require('@/app/stock').default;

test('неподтверждённый возврат: подсказка и подтверждение «вернулся на склад»', async () => {
  await render(<StockScreen />);
  expect(screen.getByText(/Подтвердите возврат на склад: 2 шт\./)).toBeTruthy();
  await fireEvent.press(screen.getByRole('button', { name: 'Вернулся на склад' }));
  expect(mockConfirm).toHaveBeenCalledWith({ productId: 'p1', sellable: true });
  await fireEvent.press(screen.getByRole('button', { name: 'Не вернулся или брак' }));
  expect(mockConfirm).toHaveBeenCalledWith({ productId: 'p1', sellable: false });
});
