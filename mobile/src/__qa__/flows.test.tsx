// 1.11: нажатия и формы в критичных сценариях — удаление аккаунта и подключение Kaspi.
// render в RNTL 14 — промис (await). Состояние обновляется асинхронно: проверки — через waitFor.
import { fireEvent, render, screen, waitFor } from '@testing-library/react-native';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

import DeleteAccountScreen from '@/app/settings/delete-account';
import KaspiScreen from '@/app/settings/kaspi';

jest.mock('expo-haptics', () => ({ selectionAsync: jest.fn(async () => undefined) }));

const mockStartMutate = jest.fn((_: unknown, opts?: { onSuccess?: () => void }) => opts?.onSuccess?.());
const mockConfirmAsync = jest.fn(async (_code: string) => ({ status: 'ok' }));
const mockLogout = jest.fn(async () => undefined);
const mockReplace = jest.fn();
const mockRequest = jest.fn();
const mockFlags = { kaspi: true };

jest.mock('expo-router', () => ({
  useRouter: () => ({ push: jest.fn(), back: jest.fn(), replace: mockReplace }),
  useLocalSearchParams: () => ({}),
}));

jest.mock('@/session/SessionProvider', () => ({
  useSession: () => ({ email: 'seller@example.invalid', logout: mockLogout, locale: 'ru', shopId: 'shop-1', isDemo: false }),
}));

jest.mock('@/api/hooks', () => ({
  useDeleteAccountStart: () => ({ mutate: mockStartMutate, isPending: false }),
  useDeleteAccountConfirm: () => ({ mutateAsync: mockConfirmAsync, isPending: false }),
  useDeactivateConfirm: () => ({ mutateAsync: jest.fn(), isPending: false }),
  useAppConfig: () => ({ data: { flags: { kaspi_connection: mockFlags.kaspi } } }),
}));

jest.mock('@/api/client', () => {
  const actual = jest.requireActual('@/api/client');
  return { ...actual, request: (...args: unknown[]) => mockRequest(...args) };
});

const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
const wrap = (node: React.ReactElement) => <QueryClientProvider client={client}>{node}</QueryClientProvider>;
const disabledOf = (name: string) => screen.getByRole('button', { name }).props.accessibilityState?.disabled;

beforeEach(() => {
  mockStartMutate.mockClear();
  mockConfirmAsync.mockClear();
  mockLogout.mockClear();
  mockReplace.mockClear();
  mockRequest.mockReset();
  mockFlags.kaspi = true;
});

describe('удаление аккаунта', () => {
  test('код отправляется один раз при открытии экрана', async () => {
    await render(wrap(<DeleteAccountScreen />));
    expect(mockStartMutate).toHaveBeenCalledTimes(1);
  });

  test('кнопка неактивна, пока не введено 6 цифр; затем удаление, выход и переход на приветствие', async () => {
    await render(wrap(<DeleteAccountScreen />));
    const button = 'Удалить аккаунт и все данные';
    fireEvent.changeText(screen.getByDisplayValue(''), '12345');
    await waitFor(() => expect(disabledOf(button)).toBeTruthy());
    fireEvent.changeText(screen.getByDisplayValue('12345'), '123456');
    await waitFor(() => expect(disabledOf(button)).toBeFalsy());
    fireEvent.press(screen.getByRole('button', { name: button }));
    await waitFor(() => expect(mockConfirmAsync).toHaveBeenCalledWith('123456'));
    await waitFor(() => expect(mockLogout).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(mockReplace).toHaveBeenCalledWith('/welcome'));
  });
});

describe('подключение Kaspi', () => {
  test('при выключенном флаге показывается заглушка, форма не появляется', async () => {
    mockFlags.kaspi = false;
    await render(wrap(<KaspiScreen />));
    expect(screen.getByText('Подключение Kaspi появится позже, после подтверждения Kaspi.')).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Подключить магазин' })).toBeNull();
  });

  test('пустые поля не отправляются: показывается подсказка', async () => {
    mockRequest.mockResolvedValue({ enabled: true, status: 'not_connected' });
    await render(wrap(<KaspiScreen />));
    fireEvent.press(await screen.findByRole('button', { name: 'Подключить магазин' }));
    await waitFor(() => expect(screen.getByText('Заполните ID продавца и ключ.')).toBeTruthy());
    expect(mockRequest).toHaveBeenCalledTimes(1); // только запрос статуса, подключения нет
  });

  test('успешное подключение отправляет данные и показывает статус «Подключено»', async () => {
    let connected = false;  // после подключения сервер отдаёт статус «active» при следующем запросе
    mockRequest.mockImplementation(async (_path: string, opts?: { method?: string }) => {
      if (opts?.method === 'POST') {
        connected = true;
        return { enabled: true, status: 'active', seller_id: 'S-1', last_sync_at: null };
      }
      return connected
        ? { enabled: true, status: 'active', seller_id: 'S-1', last_sync_at: null, price_url: '/v1/kaspi/price/x/y' }
        : { enabled: true, status: 'not_connected' };
    });
    await render(wrap(<KaspiScreen />));
    await screen.findByRole('button', { name: 'Подключить магазин' });
    const [sellerInput, tokenInput] = screen.getAllByDisplayValue('');
    fireEvent.changeText(sellerInput, 'S-1');
    fireEvent.changeText(tokenInput, 'token-0123456789');
    await waitFor(() => expect(screen.getByDisplayValue('S-1')).toBeTruthy());
    await waitFor(() => expect(screen.getByDisplayValue('token-0123456789')).toBeTruthy());
    // К-21: сначала предупреждение «токен один раз» — нажимаем «Понятно, подключить»
    const alertSpy = jest.spyOn(require('react-native').Alert, 'alert')
      .mockImplementation((...args: unknown[]) => {
        const buttons = args[2] as { text: string; onPress?: () => void }[];
        buttons.find((b) => b.text === 'Понятно, подключить')?.onPress?.();
      });
    fireEvent.press(screen.getByRole('button', { name: 'Подключить магазин' }));
    expect(alertSpy).toHaveBeenCalledWith('Подключить магазин?', expect.stringContaining('только один раз'), expect.anything());
    alertSpy.mockRestore();
    await waitFor(() =>
      expect(mockRequest).toHaveBeenCalledWith('/shops/shop-1/kaspi/connection', expect.objectContaining({
        method: 'POST', body: { seller_id: 'S-1', token: 'token-0123456789' },
      })),
    );
    await waitFor(() => expect(screen.getAllByText('Подключено').length).toBeGreaterThan(0));
  });
});
