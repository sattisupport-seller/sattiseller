// Расходы (1.11, 22.11): сумма с проверкой, период, сохранение расхода выбранного вида.
import { fireEvent, render, screen, waitFor } from '@testing-library/react-native';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

const mockSave = jest.fn(async (..._args: unknown[]) => ({}));

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
    useExpenses: () => m.hookResult({ data: { items: [] } }),
    useSaveExpense: () => m.hookResult({ mutateAsync: mockSave }),
  });
});

const ExpensesScreen = require('@/app/settings/expenses').default;

function renderExpenses() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}><ExpensesScreen /></QueryClientProvider>);
}

beforeEach(() => mockSave.mockClear());

test('пустая или неверная сумма не сохраняется', async () => {
  await renderExpenses();
  await fireEvent.press(screen.getByRole('button', { name: 'Сохранить' }));
  expect(await screen.findByText(/сумм|Сумм|число|Введите/)).toBeTruthy();
  expect(mockSave).not.toHaveBeenCalled();
});

test('сумма с пробелами и запятой сохраняется как расход на рекламу за выбранный период', async () => {
  await renderExpenses();
  await fireEvent.changeText(screen.getByLabelText('Сумма'), '12 500,50');
  await fireEvent.press(screen.getByRole('button', { name: 'Сохранить' }));
  await waitFor(() => expect(mockSave).toHaveBeenCalledTimes(1));
  const payload = mockSave.mock.calls[0][0] as { kind: string; amount: string; period_start: string; period_end: string };
  expect(payload.kind).toBe('ads');
  expect(payload.amount).toBe('12500.50');
  expect(payload.period_start <= payload.period_end).toBe(true);
});
