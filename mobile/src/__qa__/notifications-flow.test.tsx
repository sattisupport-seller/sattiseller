// 3.4 (К-21): настройки уведомлений читаются с сервера; меняется только нажатый пункт; разрешение — при включении;
// токен регистрируется на сервере; нажатие на уведомление открывает экран и пишет notification_opened.
import { fireEvent, render, screen, waitFor } from '@testing-library/react-native';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

const mockPatch = jest.fn();
const mockRequest = jest.fn(async (..._a: unknown[]) => ({}));
const mockTrack = jest.fn();

jest.mock('expo-haptics', () => ({ selectionAsync: jest.fn(() => Promise.resolve()) }));
jest.mock('expo-router', () => ({ useRouter: () => ({ push: jest.fn(), back: jest.fn(), replace: jest.fn() }), useLocalSearchParams: () => ({}) }));
jest.mock('@/session/SessionProvider', () => ({ useSession: () => ({ isDemo: false, locale: 'ru' }) }));
jest.mock('@/lib/analytics', () => ({ trackEvent: (...a: unknown[]) => mockTrack(...a) }));
jest.mock('@/api/client', () => ({ request: (...a: unknown[]) => mockRequest(...a), ApiError: class extends Error {} }));
jest.mock('@/api/hooks', () => {
  const m = require('./screenMocks');
  return m.hooksMock({
    useNotificationSettingsQuery: () => m.hookResult({ data: { product_in_minus: false, weekly_summary: true, quiet_hours: true } }),
    useNotificationSettings: () => m.hookResult({ mutate: mockPatch }),
  });
});

const Notifications = require('expo-notifications');
const Screen = require('@/app/settings/notifications').default;
const push = require('@/lib/push');

function renderScreen() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}><Screen /></QueryClientProvider>);
}

beforeEach(() => { mockPatch.mockClear(); mockRequest.mockClear(); mockTrack.mockClear(); Notifications.__setPermission('undetermined'); });

test('настройки с сервера показаны как есть', async () => {
  await renderScreen();
  expect(screen.getByLabelText('Еженедельная сводка (понедельник, 9:00)').props.value).toBe(true);
  expect(screen.getByLabelText('Тихие часы').props.value).toBe(true);
});

test('включение пункта меняет только его и регистрирует токен устройства', async () => {
  await renderScreen();
  await fireEvent(screen.getByLabelText('Товар ушёл в минус'), 'valueChange', true);
  expect(mockPatch).toHaveBeenCalledWith({ product_in_minus: true });
  await waitFor(() => expect(mockRequest).toHaveBeenCalledWith('/devices/push-token', {
    method: 'POST', body: { token: 'ExponentPushToken[test-device]', platform: expect.any(String) } }));
});

test('запрет уведомлений — понятный текст и путь в настройки телефона', async () => {
  Notifications.__setPermission('denied');
  await renderScreen();
  await fireEvent(screen.getByLabelText('Товар ушёл в минус'), 'valueChange', true);
  expect(await screen.findByText(/Уведомления запрещены в настройках телефона/)).toBeTruthy();
  expect(mockRequest).not.toHaveBeenCalledWith('/devices/push-token', expect.anything());
});

test('нажатие на уведомление склада открывает склад и пишет событие', () => {
  const open = jest.fn();
  const stop = push.listenForTaps(open);
  Notifications.__tap({ screen: 'stock', productId: 'p1' });
  expect(open).toHaveBeenCalledWith('/stock');
  expect(mockTrack).toHaveBeenCalledWith('notification_opened');
  stop();
});
