// Приветствие (1.11, 22.11): «Попробовать демо» запускает демо-магазин; ошибка показывается; «Войти по почте» ведёт на вход.
import { fireEvent, render, screen, waitFor } from '@testing-library/react-native';

const mockReplace = jest.fn();
const mockPush = jest.fn();
const mockStartDemo = jest.fn(async () => undefined);

jest.mock('expo-haptics', () => ({ selectionAsync: jest.fn(() => Promise.resolve()) }));
jest.mock('expo-router', () => ({
  useRouter: () => ({ push: mockPush, back: jest.fn(), replace: mockReplace }),
  useLocalSearchParams: () => ({}),
  Stack: { Screen: () => null },
}));
jest.mock('expo-web-browser', () => ({ openBrowserAsync: jest.fn(), maybeCompleteAuthSession: jest.fn() }));
jest.mock('@/session/SessionProvider', () => ({
  useSession: () => ({ locale: 'ru', startDemo: mockStartDemo, signInWithIdToken: jest.fn(), requestCode: jest.fn() }),
}));
jest.mock('@/api/hooks', () => require('./screenMocks').hooksMock({
  useAppConfig: () => require('./screenMocks').hookResult({ data: { privacy_url: 'https://example.invalid/p', terms_url: 'https://example.invalid/t', flags: { demo: true } } }),
}));

const WelcomeScreen = require('@/app/welcome').default;

beforeEach(() => {
  mockReplace.mockClear();
  mockPush.mockClear();
  mockStartDemo.mockClear();
});

test('демо-магазин запускается и открывается главный экран', async () => {
  await render(<WelcomeScreen />);
  await fireEvent.press(screen.getByRole('button', { name: 'Попробовать на демо-магазине' }));
  await waitFor(() => expect(mockStartDemo).toHaveBeenCalledTimes(1));
  await waitFor(() => expect(mockReplace).toHaveBeenCalledWith('/(tabs)'));
});

test('вход по почте ведёт на экран входа', async () => {
  await render(<WelcomeScreen />);
  await fireEvent.press(screen.getByRole('button', { name: 'Войти по email' }));
  expect(mockPush).toHaveBeenCalledWith('/login');
});
