// Ассистент (1.11, 22.11): ответ появляется, по кнопке «Пожаловаться» выбирается причина и оценка уходит на сервер.
import { fireEvent, render, screen, waitFor } from '@testing-library/react-native';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

const mockAsk = jest.fn(async (..._a: unknown[]) => ({
  turnId: 'turn-1',
  conversationId: 'conv-1',
  renderedAnswer: 'За 7 дней прибыль 10 865 ₸.',
  confidence: 'high',
  confidenceReason: '',
  dataAsOf: '2026-11-22T10:00:00Z',
  evidence: [],
  missingData: [],
  suggestedActions: [],
  lang: 'ru',
  refused: false,
  generatedBy: 'ai',
}));
const mockFeedback = jest.fn(async (..._a: unknown[]) => ({ id: 'f1' }));

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
    useAsk: () => m.hookResult({ mutateAsync: mockAsk }),
    useFeedback: () => m.hookResult({ mutate: mockFeedback }),
    useConversations: () => m.hookResult({ data: { items: [] } }),
  });
});

const AssistantScreen = require('@/app/(tabs)/assistant').default;

function renderScreen() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}><AssistantScreen /></QueryClientProvider>);
}

beforeEach(() => {
  mockAsk.mockClear();
  mockFeedback.mockClear();
});

test('ответ помощника показывается, жалоба уходит с причиной и номером хода', async () => {
  await renderScreen();
  await fireEvent.changeText(await screen.findByLabelText('Спросите о магазине…'), 'Какая прибыль за неделю?');
  await fireEvent.press(screen.getByRole('button', { name: 'Применить' }));
  expect(await screen.findByText('За 7 дней прибыль 10 865 ₸.')).toBeTruthy();
  await fireEvent.press(screen.getByRole('button', { name: 'Пожаловаться на ответ' }));
  await fireEvent.press(await screen.findByRole('button', { name: 'Неверные цифры' }));
  await waitFor(() => expect(mockFeedback).toHaveBeenCalledWith({
    shop_id: 'shop-1', turn_id: 'turn-1', kind: 'flag', reason: 'wrong_numbers',
  }));
});
