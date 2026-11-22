// Ассистент (1.11, 22.11): история диалогов открывает прежний диалог с его ответами; «Новый диалог» очищает ленту.
import { fireEvent, render, screen, waitFor } from '@testing-library/react-native';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

const mockRequest = jest.fn(async (path: string) => {
  if (path === '/ai/conversations/c1') {
    return {
      id: 'c1',
      turns: [{
        id: 't1', question: 'Прибыль за неделю',
        answer: { turnId: 't1', conversationId: 'c1', renderedAnswer: 'Прибыль 10 865 ₸.', confidence: 'high',
          confidenceReason: '', dataAsOf: '2026-11-22T10:00:00Z', evidence: [], missingData: [], suggestedActions: [],
          lang: 'ru', refused: false, generatedBy: 'ai' },
      }],
    };
  }
  return {};
});

jest.mock('@/api/client', () => ({
  request: (...a: unknown[]) => (mockRequest as unknown as (...x: unknown[]) => unknown)(...a),
  ApiError: class extends Error { status = 0; },
}));
jest.mock('expo-haptics', () => ({ selectionAsync: jest.fn(() => Promise.resolve()) }));
jest.mock('expo-router', () => ({
  useRouter: () => ({ push: jest.fn(), back: jest.fn(), replace: jest.fn() }),
  useLocalSearchParams: () => ({}),
  Stack: { Screen: () => null },
}));
jest.mock('expo-clipboard', () => ({ setStringAsync: jest.fn(async () => true) }));
jest.mock('@/components/ui/Overlays', () => ({ ...jest.requireActual('@/components/ui/Overlays'), useToast: () => ({ show: jest.fn() }) }));
jest.mock('@/session/SessionProvider', () => ({ useSession: () => ({ shopId: 'shop-1', isDemo: true, locale: 'ru' }) }));
jest.mock('@/api/hooks', () => {
  const m = require('./screenMocks');
  return m.hooksMock({
    useAIQuota: () => m.hookResult({ data: { remaining: 20, limit: 30, consent_active: true, consent_version: 'v1' } }),
    useConversations: () => m.hookResult({ data: { items: [{ id: 'c1', title: 'Прибыль за неделю', created_at: '2026-11-22T10:00:00Z' }] } }),
    useDeleteConversation: () => m.hookResult({ mutate: jest.fn() }),
  });
});

const AssistantScreen = require('@/app/(tabs)/assistant').default;

function renderScreen() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}><AssistantScreen /></QueryClientProvider>);
}

beforeEach(() => mockRequest.mockClear());

test('из истории открывается прежний диалог с ответом', async () => {
  await renderScreen();
  await fireEvent.press(screen.getByRole('button', { name: 'История диалогов' }));
  await fireEvent.press(await screen.findByText('Прибыль за неделю'));
  await waitFor(() => expect(mockRequest).toHaveBeenCalledWith('/ai/conversations/c1'));
  expect(await screen.findByText('Прибыль 10 865 ₸.')).toBeTruthy();
  expect(screen.getByText('Прибыль за неделю', { exact: true })).toBeTruthy();
});

test('«Новый диалог» очищает ленту', async () => {
  await renderScreen();
  await fireEvent.press(screen.getByRole('button', { name: 'История диалогов' }));
  await fireEvent.press(await screen.findByText('Прибыль за неделю'));
  await screen.findByText('Прибыль 10 865 ₸.');
  await fireEvent.press(screen.getByRole('button', { name: 'Новый диалог' }));
  expect(screen.queryByText('Прибыль 10 865 ₸.')).toBeNull();
});
