// Подписка закончилась (1.11, 22.11): дата удаления данных, переход к оплате, выход и удаление аккаунта, ссылки.
import { fireEvent, render, screen, waitFor } from '@testing-library/react-native';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { Linking } from 'react-native';

const mockPush = jest.fn();
const mockLogout = jest.fn(async () => undefined);

jest.mock('expo-haptics', () => ({ selectionAsync: jest.fn(() => Promise.resolve()) }));
jest.mock('expo-router', () => ({
  useRouter: () => ({ push: mockPush, back: jest.fn(), replace: jest.fn() }),
  useLocalSearchParams: () => ({}),
  Stack: { Screen: () => null },
}));
jest.mock('@/components/ui/Overlays', () => ({ ...jest.requireActual('@/components/ui/Overlays'), useToast: () => ({ show: jest.fn() }) }));
jest.mock('@/session/SessionProvider', () => ({ useSession: () => ({ shopId: 'shop-1', isDemo: false, locale: 'ru', logout: mockLogout }) }));
jest.mock('@/api/hooks', () => {
  const m = require('./screenMocks');
  return m.hooksMock({
    useSubscription: () => m.hookResult({ data: { data_delete_on: '2026-12-22' } }),
    useAppConfig: () => m.hookResult({ data: { privacy_url: 'https://example.invalid/p', terms_url: 'https://example.invalid/t' } }),
  });
});

const SubscriptionEnded = require('@/app/subscription-ended').default;

function renderScreen() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}><SubscriptionEnded /></QueryClientProvider>);
}

beforeEach(() => {
  mockPush.mockClear();
  mockLogout.mockClear();
});

test('кнопка оформления ведёт на оплату, выход выполняется', async () => {
  await renderScreen();
  await fireEvent.press(screen.getByRole('button', { name: 'Оформить подписку' }));
  expect(mockPush).toHaveBeenCalledWith('/paywall');
  await fireEvent.press(screen.getByText('Выйти'));
  await waitFor(() => expect(mockLogout).toHaveBeenCalled());
});

test('ссылки на политику и условия открываются из конфигурации приложения', async () => {
  const open = jest.spyOn(Linking, 'openURL').mockResolvedValue(undefined);
  await renderScreen();
  await fireEvent.press(screen.getByText('Политика конфиденциальности'));
  expect(open).toHaveBeenCalledWith('https://example.invalid/p');
  await fireEvent.press(screen.getByText('Условия использования'));
  expect(open).toHaveBeenCalledWith('https://example.invalid/t');
  open.mockRestore();
});

test('удаление аккаунта ведёт на экран удаления', async () => {
  await renderScreen();
  await fireEvent.press(screen.getByText('Удалить аккаунт'));
  expect(mockPush).toHaveBeenCalledWith('/settings/delete-account');
});
