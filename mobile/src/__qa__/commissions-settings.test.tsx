// Комиссии по категориям (1.11, 22.11): выбор категории, проверка ставки, сохранение.
import { fireEvent, render, screen, waitFor } from '@testing-library/react-native';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

const mockSave = jest.fn(async (..._args: unknown[]) => ({}));
const ITEMS = [{ id: 'c1', category: 'Посуда', rate_bp: 1000, effective_from: '2026-01-01', demo: true, verified: false }];

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
    useCommissions: () => m.hookResult({ data: { items: [{ id: 'c1', category: 'Посуда', rate_bp: 1000, effective_from: '2026-01-01', demo: true, verified: false }] } }),
    useSaveCommission: () => m.hookResult({ mutateAsync: mockSave }),
  });
});

const CommissionsScreen = require('@/app/settings/commissions').default;

function renderCommissions() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}><CommissionsScreen /></QueryClientProvider>);
}

beforeEach(() => mockSave.mockClear());

test('ставка вне формата не сохраняется', async () => {
  await renderCommissions();
  await fireEvent.press(screen.getByText('Посуда'));
  await fireEvent.changeText(screen.getByLabelText('Ставка, %'), 'десять');
  await fireEvent.press(screen.getByRole('button', { name: 'Сохранить' }));
  expect(await screen.findByText('Проверьте интернет и попробуйте снова.')).toBeTruthy();
  expect(mockSave).not.toHaveBeenCalled();
});

test('выбранная категория сохраняется с новой ставкой', async () => {
  await renderCommissions();
  await fireEvent.press(screen.getByText('Посуда'));
  await fireEvent.changeText(screen.getByLabelText('Ставка, %'), '12,5');
  await fireEvent.press(screen.getByRole('button', { name: 'Сохранить' }));
  await waitFor(() => expect(mockSave).toHaveBeenCalledWith({ category: 'Посуда', rate_percent: '12,5', effective_from: null }));
});
