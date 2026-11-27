// Черновик описания (К-12; К-24 — отдельного согласия на ИИ нет, оно в галочке условий). Исчерпанная квота — понятная фраза, а не код ошибки.
import { fireEvent, render, screen, waitFor } from '@testing-library/react-native';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ApiError } from '@/api/client';

const draftOk = {
  titles: ['Термокружка 450 мл'],
  description: 'Термокружка из нержавеющей стали.',
  characteristics: [{ name: 'Материал', value: 'нержавейка' }],
  warnings: [],
  generatedBy: 'ai',
};
const mockDraft = jest.fn(async (..._a: unknown[]) => draftOk);
const mockConsent = jest.fn(async (..._a: unknown[]) => ({ consent_active: true, consent_version: 'v1', service: 'Satti AI' }));

jest.mock('expo-haptics', () => ({ selectionAsync: jest.fn(() => Promise.resolve()) }));
jest.mock('expo-router', () => ({
  useRouter: () => ({ push: jest.fn(), back: jest.fn(), replace: jest.fn() }),
  useLocalSearchParams: () => ({}),
  Stack: { Screen: () => null },
}));
jest.mock('expo-document-picker', () => ({ getDocumentAsync: jest.fn(async () => ({ canceled: true, assets: [] })) }));
jest.mock('expo-image-picker', () => ({ requestCameraPermissionsAsync: jest.fn(async () => ({ granted: false })), launchCameraAsync: jest.fn() }));
jest.mock('expo-clipboard', () => ({ setStringAsync: jest.fn(async () => true) }));
jest.mock('@/components/ui/Overlays', () => ({ ...jest.requireActual('@/components/ui/Overlays'), useToast: () => ({ show: jest.fn() }) }));
jest.mock('@/session/SessionProvider', () => ({ useSession: () => ({ shopId: 'shop-1', isDemo: true, locale: 'ru' }) }));
jest.mock('@/api/hooks', () => {
  const m = require('./screenMocks');
  return m.hooksMock({
    useProductDraft: () => m.hookResult({ mutateAsync: mockDraft }),
    useAIConsent: () => m.hookResult({ mutateAsync: mockConsent }),
  });
});

const ProductDraftScreen = require('@/app/assistant/product-draft').default;

function renderScreen() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}><ProductDraftScreen /></QueryClientProvider>);
}

beforeEach(() => {
  mockDraft.mockReset();
  mockDraft.mockResolvedValue(draftOk);
  mockConsent.mockClear();
});

test('К-24: отдельного экрана согласия нет — черновик создаётся сразу', async () => {
  await renderScreen();
  await fireEvent.changeText(screen.getByLabelText('Факты о товаре'), 'Термокружка нержавейка 450 мл');
  await fireEvent.press(screen.getByRole('button', { name: 'Составить описание' }));
  expect(await screen.findByText('Термокружка 450 мл')).toBeTruthy();
  expect(mockDraft).toHaveBeenCalledTimes(1);
  expect(screen.queryByText('Помощник использует ИИ')).toBeNull();
  expect(mockConsent).not.toHaveBeenCalled();
});

test('К-24: условия не приняты — понятный текст сервера, без экрана согласия', async () => {
  mockDraft.mockRejectedValueOnce(new ApiError(403, 'terms_consent_required', 'Примите обновлённые условия и политику конфиденциальности.'));
  await renderScreen();
  await fireEvent.changeText(screen.getByLabelText('Факты о товаре'), 'Термокружка нержавейка 450 мл');
  await fireEvent.press(screen.getByRole('button', { name: 'Составить описание' }));
  expect(await screen.findByText('Примите обновлённые условия и политику конфиденциальности.')).toBeTruthy();
  expect(screen.queryByText('Помощник использует ИИ')).toBeNull();
});

test('исчерпанная квота показывает понятный текст, а не код ошибки и не экран согласия', async () => {
  mockDraft.mockRejectedValueOnce(new ApiError(429, 'ai_limit', 'limit'));
  await renderScreen();
  await fireEvent.changeText(screen.getByLabelText('Факты о товаре'), 'Термокружка нержавейка 450 мл');
  await fireEvent.press(screen.getByRole('button', { name: 'Составить описание' }));

  expect(await screen.findByText('На сегодня лимит черновиков исчерпан. Попробуйте завтра.')).toBeTruthy();
  expect(screen.queryByText('Помощник использует ИИ')).toBeNull();
  expect(mockConsent).not.toHaveBeenCalled();
});

test('шаблон вместо ИИ показывает причину в пометке', async () => {
  mockDraft.mockResolvedValueOnce({ ...draftOk, generatedBy: 'template', warnings: ['Составлено по шаблону: ИИ сейчас недоступен. Проверьте текст перед публикацией.'] } as never);
  await renderScreen();
  await fireEvent.changeText(screen.getByLabelText('Факты о товаре'), 'Термокружка нержавейка 450 мл');
  await fireEvent.press(screen.getByRole('button', { name: 'Составить описание' }));
  expect(await screen.findByText('Составлено по шаблону: ИИ сейчас недоступен. Проверьте текст перед публикацией.')).toBeTruthy();
});
