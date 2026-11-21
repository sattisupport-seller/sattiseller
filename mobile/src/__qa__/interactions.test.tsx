// 1.11: тесты нажатий в критичных сценариях. render в RNTL 14 возвращает промис: его нужно ждать (await),
// иначе screen не привязан и запросы падают с «render function has not been called».
import { fireEvent, render, screen, waitFor } from '@testing-library/react-native';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

import LoginScreen from '@/app/login';
import TermsConsentScreen from '@/app/terms-consent';

const mockAcceptTerms = jest.fn(async () => undefined);
const mockReplace = jest.fn();

jest.mock('expo-router', () => ({
  useRouter: () => ({ push: jest.fn(), back: jest.fn(), replace: mockReplace }),
  useLocalSearchParams: () => ({}),
}));

jest.mock('@/session/SessionProvider', () => ({
  useSession: () => ({
    locale: 'ru',
    requestCode: jest.fn(async () => undefined),
    signInWithIdToken: jest.fn(async () => undefined),
    acceptTerms: mockAcceptTerms,
  }),
}));

jest.mock('@/api/hooks', () => ({
  useAppConfig: () => ({
    data: { privacy_url: 'https://example.invalid/privacy', terms_url: 'https://example.invalid/terms' },
  }),
}));

const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
const wrap = (node: React.ReactElement) => <QueryClientProvider client={client}>{node}</QueryClientProvider>;

beforeEach(() => {
  mockAcceptTerms.mockClear();
  mockReplace.mockClear();
});

describe('экран входа: согласие', () => {
  test('галочка условий не отмечена по умолчанию и отмечается нажатием', async () => {
    await render(wrap(<LoginScreen />));
    const box = screen.getByRole('checkbox', { name: /Я принимаю условия/ });
    expect(box.props.accessibilityState).toEqual({ checked: false });
    fireEvent.press(box);
    await waitFor(() =>
      expect(screen.getByRole('checkbox', { name: /Я принимаю условия/ }).props.accessibilityState).toEqual({ checked: true }),
    );
  });

  test('ссылки на политику и условия есть на экране входа', async () => {
    await render(wrap(<LoginScreen />));
    expect(screen.getByRole('link', { name: 'Политика конфиденциальности' })).toBeTruthy();
    expect(screen.getByRole('link', { name: 'Условия использования' })).toBeTruthy();
  });
});

describe('экран повторного согласия (1.19)', () => {
  test('кнопка неактивна, пока галочка не отмечена', async () => {
    await render(wrap(<TermsConsentScreen />));
    fireEvent.press(screen.getByRole('button', { name: 'Принять и продолжить' }));
    expect(mockAcceptTerms).not.toHaveBeenCalled();
  });

  test('после галочки согласие сохраняется и открывается главный экран', async () => {
    await render(wrap(<TermsConsentScreen />));
    fireEvent.press(screen.getByRole('checkbox', { name: /Я принимаю условия/ }));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Принять и продолжить' }).props.accessibilityState?.disabled).toBeFalsy());
    fireEvent.press(screen.getByRole('button', { name: 'Принять и продолжить' }));
    await waitFor(() => expect(mockAcceptTerms).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(mockReplace).toHaveBeenCalledWith('/'));
  });
});
