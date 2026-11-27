// Вход по почте (1.11, 22.11): условия, проверка адреса, запрос кода и переход на экран кода.
import { fireEvent, render, screen, waitFor } from '@testing-library/react-native';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

process.env.EXPO_PUBLIC_EMAIL_LOGIN = '1';  // вход по почте включён только в этой сборке для теста

const mockPush = jest.fn();
const mockRequestCode = jest.fn(async () => undefined);

jest.mock('expo-haptics', () => ({ selectionAsync: jest.fn(() => Promise.resolve()) }));
jest.mock('expo-router', () => ({
  useRouter: () => ({ push: mockPush, back: jest.fn(), replace: jest.fn() }),
  useLocalSearchParams: () => ({}),
  Stack: { Screen: () => null },
  Link: ({ children }: { children: React.ReactNode }) => children,
}));
jest.mock('expo-web-browser', () => ({ openBrowserAsync: jest.fn(), maybeCompleteAuthSession: jest.fn() }));
jest.mock('expo-linking', () => ({ openURL: jest.fn(), createURL: (p: string) => p }));
jest.mock('@/session/SessionProvider', () => ({
  useSession: () => ({ shopId: null, isDemo: false, locale: 'ru', requestCode: mockRequestCode, signInWithIdToken: jest.fn(), acceptTerms: jest.fn() }),
}));
jest.mock('@/api/hooks', () => require('./screenMocks').hooksMock({
  useAppConfig: () => require('./screenMocks').hookResult({ data: { privacy_url: 'https://example.invalid/p', terms_url: 'https://example.invalid/t' } }),
}));

const LoginScreen = require('@/app/login').default;

function renderLogin() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}><LoginScreen /></QueryClientProvider>);
}

beforeEach(() => {
  mockPush.mockClear();
  mockRequestCode.mockClear();
});

test('без галочки условий код не запрашивается', async () => {
  await renderLogin();
  await fireEvent.changeText(screen.getByLabelText('Email'), 'seller@example.invalid');
  await fireEvent.press(screen.getByRole('button', { name: 'Получить код' }));
  expect(await screen.findByText('Сначала примите условия использования и политику конфиденциальности.')).toBeTruthy();
  expect(mockRequestCode).not.toHaveBeenCalled();
});

test('неверный адрес почты показывает ошибку', async () => {
  await renderLogin();
  await fireEvent.press(screen.getByRole('checkbox', { name: /Я принимаю условия/ }));
  await fireEvent.changeText(screen.getByLabelText('Email'), 'не-почта');
  await fireEvent.press(screen.getByRole('button', { name: 'Получить код' }));
  expect(await screen.findByText('Проверьте адрес почты')).toBeTruthy();
  expect(mockRequestCode).not.toHaveBeenCalled();
});

test('с галочкой и адресом код запрашивается и открывается экран кода', async () => {
  await renderLogin();
  await fireEvent.press(screen.getByRole('checkbox', { name: /Я принимаю условия/ }));
  await fireEvent.changeText(screen.getByLabelText('Email'), '  Seller@Example.invalid ');
  await fireEvent.press(screen.getByRole('button', { name: 'Получить код' }));
  await waitFor(() => expect(mockRequestCode).toHaveBeenCalledWith('seller@example.invalid'));
  await waitFor(() => expect(mockPush).toHaveBeenCalledWith({ pathname: '/code', params: { email: 'seller@example.invalid', accepted: '1' } }));
});

test('К-24: согласие на ИИ — в той же галочке, отдельной строкой рядом с ней', async () => {
  await renderLogin();
  expect(screen.getByRole('checkbox', { name: /включая передачу данных ИИ-сервису/ })).toBeTruthy();
  expect(screen.getByText('Помощник и карточки товаров работают на ИИ компании Anthropic (США). Данные покупателей перед отправкой скрываются.')).toBeTruthy();
});
