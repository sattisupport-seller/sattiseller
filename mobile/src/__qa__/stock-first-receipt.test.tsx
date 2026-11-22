// Склад, первый приход у нового продавца (К-4, 22.11): вместо ошибки — окно «Сначала укажите остаток»,
// после инвентаризации (можно 0) приход уходит сам, с тем же количеством.
import { fireEvent, render, screen, waitFor } from '@testing-library/react-native';
import { ApiError } from '@/api/client';

const mockReceipt = jest.fn(async (..._a: unknown[]) => ({ qty: 3, current: 3 }));
const mockInventory = jest.fn(async (..._a: unknown[]) => ({ qty: 0 }));

jest.mock('expo-haptics', () => ({ selectionAsync: jest.fn(() => Promise.resolve()) }));
jest.mock('expo-router', () => ({
  useRouter: () => ({ push: jest.fn(), back: jest.fn(), replace: jest.fn() }),
  useLocalSearchParams: () => ({}),
  Stack: { Screen: () => null },
}));
jest.mock('@/components/ui/Overlays', () => ({ ...jest.requireActual('@/components/ui/Overlays'), useToast: () => ({ show: jest.fn() }) }));
jest.mock('@/session/SessionProvider', () => ({ useSession: () => ({ shopId: 'shop-1', isDemo: true, locale: 'ru' }) }));
jest.mock('@/api/hooks', () => {
  const m = require('./screenMocks');
  return m.hooksMock({
    useStockList: () => m.hookResult({ data: { items: [] } }),
    useStockAlerts: () => m.hookResult({ data: { items: [], endingSoon: [] } }),
    useProducts: () => m.hookResult({ data: { pages: [{ items: [{ product_id: 'p1', sku: 'D007', name: 'Термокружка' }] }] } }),
    useStockMutations: () => ({
      receipt: m.hookResult({ mutateAsync: mockReceipt }),
      inventory: m.hookResult({ mutateAsync: mockInventory }),
      delist: m.hookResult({ mutateAsync: jest.fn() }),
      relist: m.hookResult({ mutate: jest.fn() }),
    }),
  });
});

const StockScreen = require('@/app/stock').default;

beforeEach(() => {
  mockReceipt.mockReset();
  mockInventory.mockReset();
  mockReceipt.mockRejectedValueOnce(new ApiError(409, 'stock_not_counted', 'сначала инвентаризация'));
  mockReceipt.mockResolvedValue({ qty: 3, current: 3 });
  mockInventory.mockResolvedValue({ qty: 0 });
});

test('первый приход без инвентаризации ведёт к вводу остатка и затем повторяет приход', async () => {
  await render(<StockScreen />);
  await fireEvent.press(screen.getByRole('button', { name: 'Приход' }));
  await fireEvent.changeText(await screen.findByLabelText('Количество, шт.'), '3');
  await fireEvent.press(screen.getByRole('button', { name: 'Сохранить' }));

  expect(await screen.findByText('Сначала укажите остаток')).toBeTruthy();
  expect(screen.queryByText('Введите целое число больше нуля')).toBeNull();

  await fireEvent.press(screen.getByRole('button', { name: 'Указать остаток' }));
  await fireEvent.changeText(await screen.findByLabelText('Количество, шт.'), '0');
  await fireEvent.press(screen.getByRole('button', { name: 'Сохранить' }));

  await waitFor(() => expect(mockInventory).toHaveBeenCalledWith({ productId: 'p1', qty: 0 }));
  await waitFor(() => expect(mockReceipt).toHaveBeenCalledTimes(2));
  expect(mockReceipt.mock.calls[1][0]).toEqual({ productId: 'p1', qty: 3 });
});
