// Удаление аккаунта (1.11, 22.11): код отправляется при открытии; подтверждение кнопкой только с шестью цифрами.
import { fireEvent, render, screen, waitFor } from '@testing-library/react-native';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

const mockStart = jest.fn((_v?: unknown, opts?: { onSuccess?: () => void }) => { opts?.onSuccess?.(); });
const mockConfirm = jest.fn(async (..._a: unknown[]) => ({}));
const mockLogout = jest.fn(async () => undefined);
const mockReplace = jest.fn();

jest.mock('expo-haptics', () => ({ selectionAsync: jest.fn(() => Promise.resolve()) }));
jest.mock('expo-router', () => ({
  useRouter: () => ({ push: jest.fn(), back: jest.fn(), replace: mockReplace }),
  useLocalSearchParams: () => ({}),
  Stack: { Screen: () => null },
}));
jest.mock('@/components/ui/Overlays', () => ({ ...jest.requireActual('@/components/ui/Overlays'), useToast: () => ({ show: jest.fn() }) }));
jest.mock('@/session/SessionProvider', () => ({ useSession: () => ({ email: 'seller@example.invalid', logout: mockLogout, locale: 'ru' }) }));
jest.mock('@/api/hooks', () => {
  const m = require('./screenMocks');
  return m.hooksMock({
    useDeleteAccountStart: () => m.hookResult({ mutate: mockStart }),
    useDeleteAccountConfirm: () => m.hookResult({ mutateAsync: mockConfirm }),
  });
});

const DeleteAccountScreen = require('@/app/settings/delete-account').default;

function renderScreen() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}><DeleteAccountScreen /></QueryClientProvider>);
}

beforeEach(() => {
  mockStart.mockClear();
  mockConfirm.mockClear();
  mockLogout.mockClear();
  mockReplace.mockClear();
});

test('код для удаления запрашивается при открытии экрана', async () => {
  await renderScreen();
  expect(mockStart).toHaveBeenCalledTimes(1);
});

test('кнопка удаления не работает, пока код не из шести цифр', async () => {
  await renderScreen();
  await fireEvent.changeText(screen.getByLabelText('Код'), '1234');
  await fireEvent.press(screen.getByRole('button', { name: 'Удалить аккаунт навсегда' }));
  expect(mockConfirm).not.toHaveBeenCalled();
});

test('с правильным кодом аккаунт удаляется, выполняется выход и переход на приветствие', async () => {
  await renderScreen();
  await fireEvent.changeText(screen.getByLabelText('Код'), '654321');
  await fireEvent.press(screen.getByRole('button', { name: 'Удалить аккаунт навсегда' }));
  await waitFor(() => expect(mockConfirm).toHaveBeenCalledWith('654321'));
  await waitFor(() => expect(mockLogout).toHaveBeenCalled());
  await waitFor(() => expect(mockReplace).toHaveBeenCalledWith('/welcome'));
});
