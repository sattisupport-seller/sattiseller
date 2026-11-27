// Быстрый ввод (1.11; К-24): себестоимость и остаток — два обязательных поля; остаток из прайса подставляется;
// некорректная цена не сохраняется; заполненные товары уходят пакетом.
import { fireEvent, render, screen, waitFor } from '@testing-library/react-native';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

const mockBulk = jest.fn(async (..._a: unknown[]) => ({}));
const mockBack = jest.fn();

jest.mock('expo-haptics', () => ({ selectionAsync: jest.fn(() => Promise.resolve()) }));
jest.mock('expo-router', () => ({
  useRouter: () => ({ push: jest.fn(), back: mockBack, replace: jest.fn() }),
  useLocalSearchParams: () => ({}),
  Stack: { Screen: () => null },
}));
jest.mock('@/components/ui/Overlays', () => ({ ...jest.requireActual('@/components/ui/Overlays'), useToast: () => ({ show: jest.fn() }) }));
jest.mock('@/session/SessionProvider', () => ({ useSession: () => ({ shopId: 'shop-1', isDemo: false, locale: 'ru' }) }));
jest.mock('@/api/hooks', () => {
  const m = require('./screenMocks');
  return m.hooksMock({
    useMissingCosts: () => m.hookResult({ data: { items: [
      { product_id: 'p1', sku: 'D007', name: 'Термокружка', needs_cost: true, needs_stock: true, stock_hint: null },
      { product_id: 'p2', sku: 'D008', name: 'Коврик', needs_cost: true, needs_stock: true, stock_hint: 7 },
      { product_id: 'p3', sku: 'D009', name: 'Чайник', needs_cost: false, needs_stock: true, stock_hint: null },
    ] } }),
    useBulkCost: () => m.hookResult({ mutateAsync: mockBulk }),
  });
});

const QuickCostScreen = require('@/app/quick-cost').default;

function renderScreen() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}><QuickCostScreen /></QueryClientProvider>);
}

const saveButton = () => screen.getByRole('button', { name: /^Сохранить/ });

beforeEach(() => {
  mockBulk.mockClear();
  mockBack.mockClear();
});

test('К-24: только себестоимость без остатка — товар не сохраняется', async () => {
  await renderScreen();
  await fireEvent.changeText(screen.getByLabelText('Термокружка: Закупка'), '2800');
  await fireEvent.press(saveButton());
  expect(mockBulk).not.toHaveBeenCalledWith(expect.objectContaining({
    items: expect.arrayContaining([expect.objectContaining({ product_id: 'p1' })]),
  }));
});

test('К-24: себестоимость и остаток уходят вместе; 0 — можно', async () => {
  await renderScreen();
  await fireEvent.changeText(screen.getByLabelText('Термокружка: Закупка'), '2 800,50');
  await fireEvent.changeText(screen.getByLabelText('Термокружка: Остаток сейчас, шт.'), '0');
  await fireEvent.press(saveButton());
  await waitFor(() => expect(mockBulk).toHaveBeenCalledTimes(1));
  expect(mockBulk.mock.calls[0][0]).toEqual(expect.objectContaining({
    items: expect.arrayContaining([{ product_id: 'p1', purchase: '2800.50', stock_qty: 0 }]),
    apply_to_history: true,
  }));
  await waitFor(() => expect(mockBack).toHaveBeenCalled());
});

test('К-24: остаток из прайса подставлен, продавец подтверждает сохранением', async () => {
  await renderScreen();
  expect(screen.getByLabelText('Коврик: Остаток сейчас, шт.').props.value).toBe('7');
  expect(screen.getByText('Взято из вашего прайс-листа Kaspi — проверьте и подтвердите.')).toBeTruthy();
  await fireEvent.changeText(screen.getByLabelText('Коврик: Закупка'), '1500');
  await fireEvent.press(saveButton());
  await waitFor(() => expect(mockBulk).toHaveBeenCalledTimes(1));
  expect(mockBulk.mock.calls[0][0]).toEqual({ items: [{ product_id: 'p2', purchase: '1500', stock_qty: 7 }], apply_to_history: true });
});

test('К-24: у товара с себестоимостью — только поле остатка', async () => {
  await renderScreen();
  expect(screen.queryByLabelText('Чайник: Закупка')).toBeNull();
  await fireEvent.changeText(screen.getByLabelText('Чайник: Остаток сейчас, шт.'), '12');
  await fireEvent.press(saveButton());
  await waitFor(() => expect(mockBulk).toHaveBeenCalledTimes(1));
  expect(mockBulk.mock.calls[0][0]).toEqual({ items: [{ product_id: 'p3', stock_qty: 12 }], apply_to_history: true });
});

test('некорректная цена не сохраняется и показывает ошибку', async () => {
  await renderScreen();
  await fireEvent.changeText(screen.getByLabelText('Термокружка: Закупка'), 'много');
  await fireEvent.changeText(screen.getByLabelText('Термокружка: Остаток сейчас, шт.'), '3');
  await fireEvent.press(saveButton());
  expect(await screen.findByText('Укажите закупочную цену')).toBeTruthy();
  expect(mockBulk).not.toHaveBeenCalled();
});
