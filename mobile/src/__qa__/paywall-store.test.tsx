// Покупка через магазин (MASTER_PLAN 3.1, К-21): предложение от сервера, покупка, проверка сервером, закрытие
// транзакции только после проверки; «Восстановить покупки»; отказ в пробном периоде на использованном телефоне.
import { fireEvent, render, screen, waitFor } from '@testing-library/react-native';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

const mockBack = jest.fn();
const mockFinish = jest.fn(async () => undefined);
const mockVerify = jest.fn(async (_body: unknown) => ({ state: 'active' }));
const mockRestore = jest.fn(async (): Promise<unknown[]> => []);
const mockOffer = jest.fn(async (_device: unknown) => ({
  trial_available: true, reason: 'ok', reason_text: null, account_token: 'acc-1',
  apple_product_id: 'kz.satti.seller.monthly', google_subscription_id: 'satti_monthly', google_offer_id: 'trial14',
  price_text: '9 900 ₸ в месяц', trial_days: 14,
}));

jest.mock('expo-haptics', () => ({ selectionAsync: jest.fn(() => Promise.resolve()) }));
jest.mock('expo-router', () => ({
  useRouter: () => ({ push: jest.fn(), back: mockBack, replace: jest.fn() }),
  useLocalSearchParams: () => ({}),
  Stack: { Screen: () => null },
}));
jest.mock('@/api/client', () => ({
  request: jest.fn(async () => ({})),
  ApiError: class extends Error { code: string; constructor(m: string, c: string) { super(m); this.code = c; } },
}));
jest.mock('@/components/ui/Overlays', () => ({ ...jest.requireActual('@/components/ui/Overlays'), useToast: () => ({ show: jest.fn() }) }));
jest.mock('@/session/SessionProvider', () => ({ useSession: () => ({ shopId: 'shop-1', isDemo: false, locale: 'ru' }) }));
jest.mock('@/lib/purchases', () => ({
  PurchaseCancelled: class extends Error {},
  PurchasesUnavailable: class extends Error {},
  purchasesAvailable: () => true,
  deviceTrust: async () => ({ platform: 'ios', device_token: 'dc-token' }),
  buySubscription: async () => ({ verify: { store: 'apple', purchase_id: '2000', platform: 'ios', device_token: 'dc-token' }, finish: mockFinish }),
  restorePurchases: () => mockRestore(),
  openManageSubscriptions: jest.fn(),
}));
jest.mock('@/api/hooks', () => {
  const m = require('./screenMocks');
  return m.hooksMock({
    useSubscription: () => m.hookResult({ data: { state: 'none', trial_available: true, price_text: '9 900 ₸ в месяц' } }),
    useSubscriptionOffer: () => m.hookResult({ mutateAsync: mockOffer }),
    useVerifyPurchase: () => m.hookResult({ mutateAsync: mockVerify }),
  });
});

const PaywallScreen = require('@/app/paywall').default;

function renderScreen() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}><PaywallScreen /></QueryClientProvider>);
}

beforeEach(() => {
  [mockBack, mockFinish, mockVerify, mockRestore, mockOffer].forEach((f) => f.mockClear());
});

test('покупка проверяется сервером, затем транзакция закрывается', async () => {
  await renderScreen();
  await waitFor(() => expect(mockOffer).toHaveBeenCalledWith({ platform: 'ios', device_token: 'dc-token' }));
  await fireEvent.press(screen.getByRole('button', { name: 'Попробовать 14 дней бесплатно' }));
  await waitFor(() => expect(mockBack).toHaveBeenCalled());
  expect(mockVerify).toHaveBeenCalledWith({ store: 'apple', purchase_id: '2000', platform: 'ios', device_token: 'dc-token' });
  expect(mockFinish).toHaveBeenCalled();
  expect(mockVerify.mock.invocationCallOrder[0]).toBeLessThan(mockFinish.mock.invocationCallOrder[0]);
});

test('пробный период отклонён сервером — понятное сообщение, экран не закрывается', async () => {
  mockVerify.mockResolvedValueOnce({ state: 'trial_denied' });
  await renderScreen();
  await waitFor(() => expect(mockOffer).toHaveBeenCalled());
  await fireEvent.press(screen.getByRole('button', { name: 'Попробовать 14 дней бесплатно' }));
  expect(await screen.findByText(/Доступ откроется после первой оплаты/)).toBeTruthy();
  expect(mockBack).not.toHaveBeenCalled();
});

test('без пробного периода — кнопка подписки и причина от сервера', async () => {
  mockOffer.mockResolvedValueOnce({
    trial_available: false, reason: 'trial_used_device', reason_text: 'Пробный период на этом телефоне уже был.',
    account_token: 'acc-1', apple_product_id: 'kz.satti.seller.monthly.notrial', google_subscription_id: 'satti_monthly',
    google_offer_id: null, price_text: '9 900 ₸ в месяц', trial_days: 14,
  } as never);
  await renderScreen();
  expect(await screen.findByText('Пробный период на этом телефоне уже был.')).toBeTruthy();
  expect(screen.getByRole('button', { name: 'Оформить подписку' })).toBeTruthy();
});

test('«Восстановить покупки» без покупок — сообщение', async () => {
  await renderScreen();
  await fireEvent.press(screen.getByRole('button', { name: 'Восстановить покупки' }));
  expect(await screen.findByText('Покупок для восстановления не найдено.')).toBeTruthy();
});

test('«Восстановить покупки» отправляет найденные покупки на проверку', async () => {
  mockRestore.mockResolvedValueOnce([{ store: 'apple', purchase_id: '1000' }]);
  await renderScreen();
  await fireEvent.press(screen.getByRole('button', { name: 'Восстановить покупки' }));
  await waitFor(() => expect(mockVerify).toHaveBeenCalledWith({ store: 'apple', purchase_id: '1000' }));
  await waitFor(() => expect(mockBack).toHaveBeenCalled());
});
