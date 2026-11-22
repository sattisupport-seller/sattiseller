// Быстрый ввод закупочных цен (1.11, 22.11): некорректная цена не сохраняется, заполненные уходят пакетом.
import { fireEvent, render, screen, waitFor } from '@testing-library/react-native';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

const mockBulk = jest.fn(async (..._a: unknown[]) => ({}));
const mockBack = jest.fn();
const ITEMS = [
  { product_id: 'p1', sku: 'D007', name: 'Термокружка' },
  { product_id: 'p2', sku: 'D008', name: 'Коврик' },
];

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
      { product_id: 'p1', sku: 'D007', name: 'Термокружка' },
      { product_id: 'p2', sku: 'D008', name: 'Коврик' },
    ] } }),
    useBulkCost: () => m.hookResult({ mutateAsync: mockBulk }),
  });
});

const QuickCostScreen = require('@/app/quick-cost').default;

function renderScreen() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}><QuickCostScreen /></QueryClientProvider>);
}

beforeEach(() => {
  mockBulk.mockClear();
  mockBack.mockClear();
});

test('некорректная цена не сохраняется и показывает ошибку', async () => {
  await renderScreen();
  await fireEvent.changeText(screen.getByLabelText('Термокружка: Закупка'), 'много');
  await fireEvent.press(screen.getByRole('button', { name: 'Сохранить 1 цены' }));
  expect(await screen.findByText('Укажите закупочную цену')).toBeTruthy();
  expect(mockBulk).not.toHaveBeenCalled();
});

test('заполненные цены уходят пакетом, остальные товары пропускаются', async () => {
  await renderScreen();
  await fireEvent.changeText(screen.getByLabelText('Термокружка: Закупка'), '2 800,50');
  await fireEvent.press(screen.getByRole('button', { name: 'Сохранить 1 цены' }));
  await waitFor(() => expect(mockBulk).toHaveBeenCalledWith({
    items: [{ product_id: 'p1', purchase: '2800.50' }],
    apply_to_history: true,
  }));
  await waitFor(() => expect(mockBack).toHaveBeenCalled());
});
