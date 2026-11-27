// Себестоимость товара (1.11, 22.11): закупка обязательна; затраты сохраняются с выбранным режимом применения.
import { fireEvent, render, screen, waitFor } from '@testing-library/react-native';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

const mockSave = jest.fn(async (..._a: unknown[]) => ({ id: 'v1' }));

jest.mock('expo-haptics', () => ({ selectionAsync: jest.fn(() => Promise.resolve()) }));
jest.mock('expo-router', () => ({
  useRouter: () => ({ push: jest.fn(), back: jest.fn(), replace: jest.fn() }),
  useLocalSearchParams: () => ({ id: 'p1' }),
  Stack: { Screen: () => null },
}));
jest.mock('@/components/ui/Overlays', () => ({ ...jest.requireActual('@/components/ui/Overlays'), useToast: () => ({ show: jest.fn() }) }));
jest.mock('@/session/SessionProvider', () => ({ useSession: () => ({ shopId: 'shop-1', isDemo: false, locale: 'ru' }) }));
jest.mock('@/api/hooks', () => {
  const m = require('./screenMocks');
  return m.hooksMock({
    useProduct: () => m.hookResult({ data: { product: { product_id: 'p1', sku: 'D007', name: 'Термокружка', sold_qty: 0 } } }),
    useCostVersions: () => m.hookResult({ data: { items: [] } }),
    useSaveCost: () => m.hookResult({ mutateAsync: mockSave }),
    useCancelCost: () => m.hookResult({ mutate: jest.fn() }),
    useMissingCosts: () => m.hookResult({ data: { items: [
      { product_id: 'p1', sku: 'D007', name: 'Термокружка', needs_cost: true, needs_stock: true, stock_hint: null }] } }),
  });
});

const CostScreen = require('@/app/product/cost/[id]').default;

function renderScreen() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}><CostScreen /></QueryClientProvider>);
}

beforeEach(() => mockSave.mockClear());

test('К-24: без остатка затраты не сохраняются; с остатком — уходят вместе', async () => {
  await renderScreen();
  await fireEvent.changeText(screen.getByLabelText('Закупка'), '2800');
  await fireEvent.press(screen.getByRole('button', { name: 'Сохранить' }));
  expect(await screen.findByText('Укажите остаток (0 — можно)')).toBeTruthy();
  expect(mockSave).not.toHaveBeenCalled();
  await fireEvent.changeText(screen.getByLabelText('Остаток сейчас, шт.'), '5');
  await fireEvent.press(screen.getByRole('button', { name: 'Сохранить' }));
  await waitFor(() => expect(mockSave).toHaveBeenCalledWith(expect.objectContaining({ purchase: '2800', stock_qty: 5 })));
});

test('без закупки затраты не сохраняются', async () => {
  await renderScreen();
  await fireEvent.press(screen.getByRole('button', { name: 'Сохранить' }));
  expect(await screen.findByText('Укажите закупочную цену')).toBeTruthy();
  expect(mockSave).not.toHaveBeenCalled();
});

test('закупка с запятой и доставка сохраняются для всей истории', async () => {
  await renderScreen();
  await fireEvent.changeText(screen.getByLabelText('Закупка'), '1 900,5');
  await fireEvent.changeText(screen.getByLabelText('Доставка до склада'), '150');
  await fireEvent.changeText(screen.getByLabelText('Остаток сейчас, шт.'), '0');
  await fireEvent.press(screen.getByRole('button', { name: 'Сохранить' }));
  await waitFor(() => expect(mockSave).toHaveBeenCalledWith({
    purchase: '1900.5',
    delivery_to_warehouse: '150',
    packaging: '0',
    other: '0',
    apply_to_history: true,
    effective_from: null,
    stock_qty: 0,
  }));
});
