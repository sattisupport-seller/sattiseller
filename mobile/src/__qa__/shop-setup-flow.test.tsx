// Создание магазина (1.11, 22.11): название, подтверждение 18+, язык, создание и переход на главный экран.
import { fireEvent, render, screen, waitFor } from '@testing-library/react-native';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

const mockReplace = jest.fn();
const mockCreateShop = jest.fn(async (..._args: unknown[]) => undefined);

jest.mock('expo-haptics', () => ({ selectionAsync: jest.fn(() => Promise.resolve()) }));
jest.mock('expo-router', () => ({
  useRouter: () => ({ push: jest.fn(), back: jest.fn(), replace: mockReplace }),
  useLocalSearchParams: () => ({}),
  Stack: { Screen: () => null },
}));
jest.mock('@/api/client', () => ({
  request: jest.fn(async () => ({})),
  ApiError: class extends Error {},
}));
jest.mock('@/session/SessionProvider', () => ({
  useSession: () => ({ shopId: null, isDemo: false, locale: 'ru', createShop: mockCreateShop }),
}));
jest.mock('@/api/hooks', () => require('./screenMocks').hooksMock());

const ShopSetupScreen = require('@/app/shop-setup').default;

function renderSetup() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}><ShopSetupScreen /></QueryClientProvider>);
}

beforeEach(() => {
  mockReplace.mockClear();
  mockCreateShop.mockClear();
});

test('без названия магазин не создаётся', async () => {
  await renderSetup();
  await fireEvent.press(screen.getByRole('checkbox'));
  await fireEvent.press(screen.getByRole('button', { name: 'Готово' }));
  // ошибка выводится тем же текстом, что и подпись поля: элементов с этим текстом больше одного
  await waitFor(() => expect(screen.getAllByText('Название магазина').length).toBeGreaterThan(1));
  expect(mockCreateShop).not.toHaveBeenCalled();
});

test('без подтверждения 18 лет магазин не создаётся', async () => {
  await renderSetup();
  await fireEvent.changeText(screen.getByLabelText('Название магазина'), 'Уют дома');
  await fireEvent.press(screen.getByRole('button', { name: 'Готово' }));
  expect(await screen.findByText('Подтвердите, что вам 18 лет или больше.')).toBeTruthy();
  expect(mockCreateShop).not.toHaveBeenCalled();
});

test('с названием и подтверждением магазин создаётся в часовом поясе Алматы', async () => {
  await renderSetup();
  await fireEvent.changeText(screen.getByLabelText('Название магазина'), '  Уют дома ');
  await fireEvent.press(screen.getByRole('checkbox'));
  await fireEvent.press(screen.getByRole('button', { name: 'Готово' }));
  await waitFor(() => expect(mockCreateShop).toHaveBeenCalledWith('Уют дома', 'Asia/Almaty', 'ru'));
  await waitFor(() => expect(mockReplace).toHaveBeenCalledWith('/'));
});
