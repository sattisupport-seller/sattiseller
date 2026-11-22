// Налог (1.11, 22.11): включение, ставка с проверкой диапазона, сохранение с выбранным периодом.
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
    useTax: () => m.hookResult({ data: { current: null, items: [] } }),
    useSaveTax: () => m.hookResult({ mutateAsync: mockSave }),
  });
});

const TaxScreen = require('@/app/settings/tax').default;

function renderTax() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}><TaxScreen /></QueryClientProvider>);
}

beforeEach(() => mockSave.mockClear());

test('ставка вне диапазона 0–30 % не сохраняется', async () => {
  await renderTax();
  await fireEvent(screen.getByLabelText('Учитывать налог'), 'valueChange', true);
  await fireEvent.changeText(screen.getByLabelText('Ставка, %'), '45');
  await fireEvent.press(screen.getByRole('button', { name: 'Сохранить' }));
  expect(await screen.findByText('Ставка от 0 до 30% с одним знаком после запятой.')).toBeTruthy();
  expect(mockSave).not.toHaveBeenCalled();
});

test('допустимая ставка сохраняется для всей истории', async () => {
  await renderTax();
  await fireEvent(screen.getByLabelText('Учитывать налог'), 'valueChange', true);
  await fireEvent.changeText(screen.getByLabelText('Ставка, %'), '3,5');
  await fireEvent.press(screen.getByRole('button', { name: 'Сохранить' }));
  await waitFor(() => expect(mockSave).toHaveBeenCalledWith({ enabled: true, rate_percent: '3,5', effective_from: null }));
});
