// К-21, часть 2, п.6: обязательное обучение. Свёрнуто дольше 5 минут — заново, меньше — тот же шаг;
// без обучения подключение Kaspi недоступно; пройденное на одном устройстве не повторяется на другом.
import { fireEvent, render, screen, waitFor } from '@testing-library/react-native';

import { parseSaved, resumeIndex } from '@/onboarding/logic';
import { TOUR_STEPS } from '@/onboarding/steps';

const mockPush = jest.fn();
const mockRequest = jest.fn(async (..._a: unknown[]) => ({}));
const mockMe: { value: Record<string, unknown> } = { value: { onboarding_done: false } };
const mockStore: Record<string, string> = {};

jest.mock('expo-router', () => ({ useRouter: () => ({ push: mockPush, back: jest.fn(), replace: jest.fn() }), useLocalSearchParams: () => ({}) }));
jest.mock('@tanstack/react-query', () => ({ ...jest.requireActual('@tanstack/react-query'), useQueryClient: () => ({ invalidateQueries: jest.fn(async () => undefined) }) }));
jest.mock('@/session/SessionProvider', () => ({ useSession: () => ({ status: 'ready', isDemo: false, termsRequired: false, shopId: 'shop-1', locale: 'ru' }) }));
jest.mock('@/api/client', () => ({ request: (...a: unknown[]) => mockRequest(...a), ApiError: class extends Error {} }));
jest.mock('@/lib/storage', () => ({
  getItem: jest.fn(async (k: string) => mockStore[k] ?? null),
  setItem: jest.fn(async (k: string, v: string) => { mockStore[k] = v; }),
  deleteItem: jest.fn(async (k: string) => { delete mockStore[k]; }),
}));
jest.mock('@/api/hooks', () => {
  const m = require('./screenMocks');
  return m.hooksMock({
    useMe: () => m.hookResult({ data: mockMe.value }),
    useAppConfig: () => m.hookResult({ data: { onboarding_restart_minutes: 5, flags: { kaspi_connection: true } } }),
  });
});

const { OnboardingProvider } = require('@/onboarding/OnboardingProvider');

beforeEach(() => { mockPush.mockClear(); mockRequest.mockClear(); Object.keys(mockStore).forEach((k) => delete mockStore[k]); });

test('свёрнуто дольше 5 минут — заново, меньше — тот же шаг', () => {
  const now = 1_000_000_000;
  expect(resumeIndex({ index: 6, leftAt: now - 6 * 60_000 }, now, 5)).toBe(0);
  expect(resumeIndex({ index: 6, leftAt: now - 4 * 60_000 }, now, 5)).toBe(6);
  expect(resumeIndex({ index: 6, leftAt: null }, now, 5)).toBe(6);
  expect(resumeIndex(null, now, 5)).toBe(0);
  expect(parseSaved('не json')).toBeNull();
});

test('новый аккаунт: тур начинается с шага 1, только «Далее», в конце отметка на сервере', async () => {
  mockMe.value = { onboarding_done: false };
  await render(<OnboardingProvider><></></OnboardingProvider>);
  expect(await screen.findByText(`Шаг 1 из ${TOUR_STEPS.length}`)).toBeTruthy();
  expect(screen.queryByText(/Пропустить/)).toBeNull();
  for (let i = 1; i < TOUR_STEPS.length; i += 1) {
    await fireEvent.press(screen.getByRole('button', { name: 'Далее' }));
  }
  await fireEvent.press(screen.getByRole('button', { name: 'Готово' }));
  await waitFor(() => expect(mockRequest).toHaveBeenCalledWith('/me/onboarding/complete', { method: 'POST' }));
  expect(mockPush).toHaveBeenLastCalledWith('/settings/kaspi');
});

test('пройдено на другом устройстве — тур не показывается', async () => {
  mockMe.value = { onboarding_done: true };
  await render(<OnboardingProvider><></></OnboardingProvider>);
  expect(screen.queryByText(/Шаг 1 из/)).toBeNull();
});

test('вернулся через 3 минуты — продолжение с того же шага', async () => {
  mockMe.value = { onboarding_done: false };
  mockStore['satti-onboarding-v1'] = JSON.stringify({ index: 4, leftAt: Date.now() - 3 * 60_000 });
  await render(<OnboardingProvider><></></OnboardingProvider>);
  expect(await screen.findByText(`Шаг 5 из ${TOUR_STEPS.length}`)).toBeTruthy();
});

test('вернулся через 10 минут — обучение заново', async () => {
  mockMe.value = { onboarding_done: false };
  mockStore['satti-onboarding-v1'] = JSON.stringify({ index: 4, leftAt: Date.now() - 10 * 60_000 });
  await render(<OnboardingProvider><></></OnboardingProvider>);
  expect(await screen.findByText(`Шаг 1 из ${TOUR_STEPS.length}`)).toBeTruthy();
});
