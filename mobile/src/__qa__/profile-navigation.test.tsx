// Профиль (1.11, 22.11): демо — сброс демо-данных и вход в аккаунт; разделы ведут на свои экраны.
import { fireEvent, render, screen, waitFor } from '@testing-library/react-native';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

const mockPush = jest.fn();
const mockReset = jest.fn((_v?: unknown, opts?: { onSuccess?: () => void }) => { opts?.onSuccess?.(); });

jest.mock('expo-haptics', () => ({ selectionAsync: jest.fn(() => Promise.resolve()) }));
jest.mock('expo-router', () => ({
  useRouter: () => ({ push: mockPush, back: jest.fn(), replace: jest.fn() }),
  useLocalSearchParams: () => ({}),
  useFocusEffect: jest.fn(),
  Stack: { Screen: () => null },
}));
jest.mock('@/components/ui/Overlays', () => ({ ...jest.requireActual('@/components/ui/Overlays'), useToast: () => ({ show: jest.fn() }) }));
jest.mock('@/session/SessionProvider', () => ({
  useSession: () => ({
    isDemo: true, email: null, locale: 'ru', themeMode: 'system',
    setLocale: jest.fn(), setThemeMode: jest.fn(), logout: jest.fn(), shopId: 'shop-1',
  }),
}));
jest.mock('@/api/hooks', () => {
  const m = require('./screenMocks');
  return m.hooksMock({
    useResetDemo: () => m.hookResult({ mutate: mockReset }),
  });
});

const ProfileScreen = require('@/app/(tabs)/profile').default;

function renderProfile() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}><ProfileScreen /></QueryClientProvider>);
}

beforeEach(() => {
  mockPush.mockClear();
  mockReset.mockClear();
});

test('в демо-режиме сброс демо-данных выполняется по нажатию', async () => {
  await renderProfile();
  await fireEvent.press(screen.getByRole('button', { name: 'Сбросить демо' }));
  await waitFor(() => expect(mockReset).toHaveBeenCalledTimes(1));
});

test('создание аккаунта ведёт на вход', async () => {
  await renderProfile();
  await fireEvent.press(screen.getByRole('button', { name: 'Создать аккаунт' }));
  expect(mockPush).toHaveBeenCalledWith('/login');
});

test('раздел импорта затрат и комиссий ведёт на свои экраны', async () => {
  await renderProfile();
  await fireEvent.press(screen.getByText('Импорт затрат'));
  expect(mockPush).toHaveBeenCalledWith('/import');
  await fireEvent.press(screen.getByText('Комиссии по категориям'));
  expect(mockPush).toHaveBeenCalledWith('/settings/commissions');
});
