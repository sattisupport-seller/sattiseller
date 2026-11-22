// Профиль (1.11, 22.11): выход из аккаунта через подтверждение и смена языка интерфейса.
import { fireEvent, render, screen, waitFor } from '@testing-library/react-native';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

const mockLogout = jest.fn(async () => undefined);
const mockSetLocale = jest.fn();

jest.mock('expo-haptics', () => ({ selectionAsync: jest.fn(() => Promise.resolve()) }));
jest.mock('expo-router', () => ({
  useRouter: () => ({ push: jest.fn(), back: jest.fn(), replace: jest.fn() }),
  useLocalSearchParams: () => ({}),
  useFocusEffect: jest.fn(),
  Stack: { Screen: () => null },
}));
jest.mock('@/session/SessionProvider', () => ({
  useSession: () => ({
    isDemo: false, email: 'seller@example.invalid', locale: 'ru', themeMode: 'system',
    setLocale: mockSetLocale, setThemeMode: jest.fn(), logout: mockLogout, shopId: 'shop-1',
  }),
}));
jest.mock('@/components/ui/Overlays', () => ({ ...jest.requireActual('@/components/ui/Overlays'), useToast: () => ({ show: jest.fn() }) }));
jest.mock('@/api/hooks', () => require('./screenMocks').hooksMock());

const ProfileScreen = require('@/app/(tabs)/profile').default;

function renderProfile() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}><ProfileScreen /></QueryClientProvider>);
}

beforeEach(() => {
  mockLogout.mockClear();
});

test('выход из аккаунта выполняется только после подтверждения', async () => {
  await renderProfile();
  await fireEvent.press(screen.getByRole('button', { name: 'Выйти' }));
  expect(mockLogout).not.toHaveBeenCalled();
  // в листе подтверждения — кнопка с тем же названием
  const confirm = screen.getAllByRole('button', { name: 'Выйти' }).at(-1)!;
  await fireEvent.press(confirm);
  await waitFor(() => expect(mockLogout).toHaveBeenCalledTimes(1));
});
