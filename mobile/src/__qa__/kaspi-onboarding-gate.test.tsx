// К-21, часть 2, п.6: без пройденного обучения подключение Kaspi недоступно.
import { render, screen } from '@testing-library/react-native';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

jest.mock('expo-haptics', () => ({ selectionAsync: jest.fn(() => Promise.resolve()) }));
jest.mock('expo-router', () => ({ useRouter: () => ({ push: jest.fn(), back: jest.fn(), replace: jest.fn() }), useLocalSearchParams: () => ({}) }));
jest.mock('@/session/SessionProvider', () => ({ useSession: () => ({ shopId: 'shop-1', isDemo: false, locale: 'ru' }) }));
jest.mock('@/onboarding/OnboardingProvider', () => ({ useTour: () => ({ active: false, index: 0, done: false, start: jest.fn() }) }));
jest.mock('@/api/client', () => ({ request: jest.fn(async () => ({ enabled: true, status: 'not_connected' })), ApiError: class extends Error {} }));
jest.mock('@/api/hooks', () => require('./screenMocks').hooksMock({
  useAppConfig: () => require('./screenMocks').hookResult({ data: { flags: { kaspi_connection: true } } }),
}));

const KaspiScreen = require('@/app/settings/kaspi').default;

test('до конца обучения формы подключения нет, есть «Пройти обучение»', async () => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  await render(<QueryClientProvider client={qc}><KaspiScreen /></QueryClientProvider>);
  expect(await screen.findByText(/Сначала пройдите обучение/)).toBeTruthy();
  expect(screen.queryByLabelText('ID продавца')).toBeNull();
  expect(screen.getByRole('button', { name: 'Пройти обучение' })).toBeTruthy();
});
