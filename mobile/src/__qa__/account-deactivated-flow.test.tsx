// К-21: экран деактивированного аккаунта — дата удаления, восстановление только с оплаченной подпиской.
import { fireEvent, render, screen, waitFor } from '@testing-library/react-native';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

const mockReactivate = jest.fn(async (): Promise<unknown> => ({ status: 'active' }));
const mockReplace = jest.fn();
const mockPush = jest.fn();

jest.mock('expo-haptics', () => ({ selectionAsync: jest.fn(() => Promise.resolve()) }));
jest.mock('expo-router', () => ({
  useRouter: () => ({ push: mockPush, back: jest.fn(), replace: mockReplace }),
  useLocalSearchParams: () => ({}),
  Stack: { Screen: () => null },
}));
jest.mock('@/components/ui/Overlays', () => ({ ...jest.requireActual('@/components/ui/Overlays'), useToast: () => ({ show: jest.fn() }) }));
jest.mock('@/session/SessionProvider', () => ({ useSession: () => ({ logout: jest.fn(), locale: 'ru' }) }));
jest.mock('@/api/client', () => ({
  ApiError: class extends Error {
    code: string;
    constructor(code: string, message: string) { super(message); this.code = code; }
  },
}));
jest.mock('@/api/hooks', () => {
  const m = require('./screenMocks');
  return m.hooksMock({
    useMe: () => m.hookResult({ data: { deactivated: true, delete_on: '2026-12-27T00:00:00+00:00' } }),
    useReactivate: () => m.hookResult({ mutateAsync: mockReactivate }),
  });
});

const Screen = require('@/app/account-deactivated').default;

function renderScreen() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}><Screen /></QueryClientProvider>);
}

beforeEach(() => { mockReactivate.mockClear(); mockReplace.mockClear(); mockPush.mockClear(); });

test('показывает дату удаления', async () => {
  await renderScreen();
  expect(screen.getByText(/27\.12\.2026/)).toBeTruthy();
});

test('с оплаченной подпиской восстанавливает и открывает приложение', async () => {
  await renderScreen();
  await fireEvent.press(screen.getByRole('button', { name: 'Восстановить' }));
  await waitFor(() => expect(mockReplace).toHaveBeenCalledWith('/'));
});

test('без подписки — понятный текст и путь к оформлению', async () => {
  const { ApiError } = require('@/api/client');
  mockReactivate.mockRejectedValueOnce(new ApiError('subscription_required', 'нет'));
  await renderScreen();
  await fireEvent.press(screen.getByRole('button', { name: 'Восстановить' }));
  await screen.findByText(/Оплаченной подписки не найдено/);
  expect(mockReplace).not.toHaveBeenCalled();
  await fireEvent.press(screen.getByRole('button', { name: 'Оформить подписку и восстановить' }));
  expect(mockPush).toHaveBeenCalledWith('/paywall');
});
