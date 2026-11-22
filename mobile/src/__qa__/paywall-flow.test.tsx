// Оплата и пробный период (1.11, 22.11): пробный период стартует; при «уже использован» и «магазин не подключён» — понятный текст.
import { fireEvent, render, screen, waitFor } from '@testing-library/react-native';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

const mockBack = jest.fn();
const mockTrial = jest.fn(async () => ({}));
type TrialErr = { code: string; message: string } | null;
const G = globalThis as unknown as { __trialError?: TrialErr };

jest.mock('expo-haptics', () => ({ selectionAsync: jest.fn(() => Promise.resolve()) }));
jest.mock('expo-router', () => ({
  useRouter: () => ({ push: jest.fn(), back: mockBack, replace: jest.fn() }),
  useLocalSearchParams: () => ({}),
  Stack: { Screen: () => null },
}));
jest.mock('@/api/client', () => ({
  request: jest.fn(async () => ({})),
  ApiError: class extends Error { code: string; constructor(m: string, c: string) { super(m); this.code = c; } },
}));
jest.mock('@/components/ui/Overlays', () => ({ ...jest.requireActual('@/components/ui/Overlays'), useToast: () => ({ show: jest.fn() }) }));
jest.mock('@/session/SessionProvider', () => ({ useSession: () => ({ shopId: 'shop-1', isDemo: false, locale: 'ru' }) }));
jest.mock('@/api/hooks', () => {
  const m = require('./screenMocks');
  return m.hooksMock({
    useSubscription: () => m.hookResult({ data: { trial_available: true, price_text: '2 990 ₸ / мес' } }),
    useStartTrial: () => m.hookResult({
      mutateAsync: async () => {
        const err = (globalThis as unknown as { __trialError?: { code: string; message: string } | null }).__trialError;
        if (err) {
          const { ApiError } = require('@/api/client');
          throw new ApiError(err.message, err.code);
        }
        return mockTrial();
      },
    }),
  });
});

const PaywallScreen = require('@/app/paywall').default;

function renderScreen() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}><PaywallScreen /></QueryClientProvider>);
}

beforeEach(() => {
  mockBack.mockClear();
  mockTrial.mockClear();
  G.__trialError = null;
});

test('пробный период стартует и экран закрывается', async () => {
  await renderScreen();
  await fireEvent.press(screen.getByRole('button', { name: 'Попробовать 14 дней бесплатно' }));
  await waitFor(() => expect(mockBack).toHaveBeenCalled());
});

test('если пробный период уже использован — понятное сообщение', async () => {
  G.__trialError = { code: 'trial_used', message: 'trial' };
  await renderScreen();
  await fireEvent.press(screen.getByRole('button', { name: 'Попробовать 14 дней бесплатно' }));
  expect(await screen.findByText(/Пробный период уже использован/)).toBeTruthy();
  expect(mockBack).not.toHaveBeenCalled();
});

test('если оплата через магазины не подключена — отдельное сообщение', async () => {
  G.__trialError = { code: 'store_not_configured', message: 'x' };
  await renderScreen();
  await fireEvent.press(screen.getByRole('button', { name: 'Попробовать 14 дней бесплатно' }));
  expect(await screen.findByText(/App Store и Google Play пока не подключено/)).toBeTruthy();
});
