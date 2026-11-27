// Подключение Kaspi (1.11, 22.11): без ID продавца или короткого ключа подключение не отправляется; с данными — отправляется.
import { fireEvent, render, screen, waitFor } from '@testing-library/react-native';
import { Alert } from 'react-native';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

const mockConnect = jest.fn(async (..._a: unknown[]) => ({ status: 'connected' }));
const mockStatus: { value: Record<string, unknown> } = {
  value: { status: 'not_connected', seller_id: null, last_sync_at: null, price_list_url: null },
};

jest.mock('expo-haptics', () => ({ selectionAsync: jest.fn(() => Promise.resolve()) }));
jest.mock('expo-router', () => ({
  useRouter: () => ({ push: jest.fn(), back: jest.fn(), replace: jest.fn() }),
  useLocalSearchParams: () => ({}),
  Stack: { Screen: () => null },
}));
jest.mock('expo-linking', () => ({ openURL: jest.fn(), createURL: (p: string) => p }));
jest.mock('@/components/ui/Overlays', () => ({ ...jest.requireActual('@/components/ui/Overlays'), useToast: () => ({ show: jest.fn() }) }));
jest.mock('@/session/SessionProvider', () => ({ useSession: () => ({ shopId: 'shop-1', isDemo: false, locale: 'ru' }) }));
jest.mock('@/api/client', () => ({
  request: jest.fn(async (path: string, opts?: { method?: string; body?: unknown }) => {
    if (opts?.method === 'POST' && path.includes('/kaspi/connection')) return mockConnect(opts.body);
    return mockStatus.value;
  }),
  ApiError: class extends Error { code = ''; status = 0; },
}));
jest.mock('@/api/hooks', () => require('./screenMocks').hooksMock({
  useAppConfig: () => require('./screenMocks').hookResult({ data: { flags: { kaspi_connection: true } } }),
}));

const KaspiScreen = require('@/app/settings/kaspi').default;

function renderScreen() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}><KaspiScreen /></QueryClientProvider>);
}

function pressInAlert(label: string | null) {
  return jest.spyOn(Alert, 'alert').mockImplementation((...args: unknown[]) => {
    const buttons = (args[2] ?? []) as { text: string; onPress?: () => void }[];
    if (label) buttons.find((b) => b.text === label)?.onPress?.();
  });
}

beforeEach(() => {
  mockConnect.mockClear();
  mockStatus.value = { status: 'not_connected', seller_id: null, last_sync_at: null, price_list_url: null };
});
afterEach(() => jest.restoreAllMocks());

test('без ID продавца или с коротким ключом подключение не отправляется', async () => {
  await renderScreen();
  await fireEvent.changeText(screen.getByLabelText('ID продавца'), 'S-1');
  await fireEvent.changeText(screen.getByLabelText('Ключ доступа (токен)'), 'short');
  await fireEvent.press(screen.getByRole('button', { name: 'Подключить магазин' }));
  expect(mockConnect).not.toHaveBeenCalled();
});

test('с ID продавца и ключом подключение отправляется без пробелов по краям', async () => {
  await renderScreen();
  await fireEvent.changeText(screen.getByLabelText('ID продавца'), ' S-1 ');
  await fireEvent.changeText(screen.getByLabelText('Ключ доступа (токен)'), '  abcdef123456  ');
  const alert = pressInAlert('Понятно, подключить');
  await fireEvent.press(screen.getByRole('button', { name: 'Подключить магазин' }));
  expect(alert.mock.calls[0][1]).toContain('Подключить токен можно только один раз');
  await waitFor(() => expect(mockConnect).toHaveBeenCalledWith({ seller_id: 'S-1', token: 'abcdef123456' }));
});

test('К-21: без «Понятно, подключить» ключ не отправляется', async () => {
  await renderScreen();
  await fireEvent.changeText(screen.getByLabelText('ID продавца'), 'S-1');
  await fireEvent.changeText(screen.getByLabelText('Ключ доступа (токен)'), 'abcdef123456');
  pressInAlert(null);  // окно закрыто «Отмена»
  await fireEvent.press(screen.getByRole('button', { name: 'Подключить магазин' }));
  expect(mockConnect).not.toHaveBeenCalled();
});

test('К-21: у подключённого магазина нет кнопки «Отключить»; окно поддержки — только тот же магазин', async () => {
  mockStatus.value = { enabled: true, status: 'token_invalid', seller_id: 'S-1', last_sync_at: null,
    reconnect_until: new Date(Date.now() + 3600_000).toISOString() };
  await renderScreen();
  await screen.findByText('Новый ключ Kaspi');
  expect(screen.queryByRole('button', { name: 'Отключить магазин' })).toBeNull();
  expect(screen.getByText(/Отдельного отключения Kaspi нет/)).toBeTruthy();
  await fireEvent.changeText(screen.getByLabelText('Ключ доступа (токен)'), 'new-token-123456');
  pressInAlert('Понятно, подключить');
  await fireEvent.press(screen.getByRole('button', { name: 'Сохранить новый ключ' }));
  await waitFor(() => expect(mockConnect).toHaveBeenCalledWith({ seller_id: 'S-1', token: 'new-token-123456' }));
});
