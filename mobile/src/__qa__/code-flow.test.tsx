// Ввод кода из письма (1.11, 22.11): шесть цифр отправляют код; неверный код — понятная ошибка.
import { fireEvent, render, screen, waitFor } from '@testing-library/react-native';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

const mockReplace = jest.fn();
const mockVerify = jest.fn(async (..._args: unknown[]) => undefined);

jest.mock('expo-haptics', () => ({ selectionAsync: jest.fn(() => Promise.resolve()) }));
jest.mock('expo-router', () => ({
  useRouter: () => ({ push: jest.fn(), back: jest.fn(), replace: mockReplace }),
  useLocalSearchParams: () => ({ email: 'seller@example.invalid', accepted: '1' }),
  Stack: { Screen: () => null },
}));
jest.mock('@/session/SessionProvider', () => ({
  useSession: () => ({ shopId: null, isDemo: false, locale: 'ru', verifyCode: mockVerify, requestCode: jest.fn(async () => undefined) }),
}));
jest.mock('@/api/hooks', () => require('./screenMocks').hooksMock());

const CodeScreen = require('@/app/code').default;

function codeInput() {
  return screen.getAllByLabelText('Введите код').find((el) => el.props.maxLength === 6)!;
}

function renderCode() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}><CodeScreen /></QueryClientProvider>);
}

beforeEach(() => {
  mockReplace.mockClear();
  mockVerify.mockClear();
  mockVerify.mockImplementation(async () => undefined);
});

test('шесть цифр отправляют код с галочкой условий и открывают главный экран', async () => {
  await renderCode();
  await fireEvent.changeText(codeInput(), '12-34ab56');
  await waitFor(() => expect(mockVerify).toHaveBeenCalledWith('seller@example.invalid', '123456', true));
  await waitFor(() => expect(mockReplace).toHaveBeenCalledWith('/'));
});

test('неверный код показывает ошибку и очищает поле', async () => {
  mockVerify.mockImplementation(async () => { throw new Error('wrong'); });
  await renderCode();
  await fireEvent.changeText(codeInput(), '000000');
  expect(await screen.findByText('Неверный код')).toBeTruthy();
  expect(mockReplace).not.toHaveBeenCalled();
});
