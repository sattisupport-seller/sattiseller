// Ответ покупателю (1.11, 22.11): без вопроса черновик не создаётся; с вопросом и тоном — создаётся и показывается.
import { fireEvent, render, screen, waitFor } from '@testing-library/react-native';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

const mockFeedback = jest.fn();
const mockReply = jest.fn(async (..._a: unknown[]) => ({ reply: 'Заказ будет доставлен завтра.', warnings: [] }));

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
    useReplyDraft: () => m.hookResult({ mutateAsync: mockReply }),
    useFeedback: () => m.hookResult({ mutate: mockFeedback }),
  });
});

const ReplyDraftScreen = require('@/app/assistant/reply-draft').default;

function renderScreen() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}><ReplyDraftScreen /></QueryClientProvider>);
}

beforeEach(() => mockReply.mockClear());

test('без вопроса покупателя ответ не составляется', async () => {
  await renderScreen();
  await fireEvent.press(screen.getByRole('button', { name: 'Составить ответ' }));
  expect(mockReply).not.toHaveBeenCalled();
});

test('с вопросом и кратким тоном ответ составляется и показывается', async () => {
  await renderScreen();
  await fireEvent.changeText(screen.getByLabelText('Вопрос покупателя'), 'Когда придёт заказ?');
  await fireEvent.press(screen.getByText('Коротко'));
  await fireEvent.press(screen.getByRole('button', { name: 'Составить ответ' }));
  await waitFor(() => expect(mockReply).toHaveBeenCalledWith({ question: 'Когда придёт заказ?', tone: 'short' }));
  expect(await screen.findByText('Заказ будет доставлен завтра.')).toBeTruthy();
});

test('Google Play: на текст ИИ можно пожаловаться прямо в приложении', async () => {
  await renderScreen();
  await fireEvent.changeText(screen.getByLabelText('Вопрос покупателя'), 'Когда придёт заказ?');
  await fireEvent.press(screen.getByRole('button', { name: 'Составить ответ' }));
  await screen.findByText('Заказ будет доставлен завтра.');
  await fireEvent.press(screen.getByRole('button', { name: 'Пожаловаться на текст ИИ' }));
  expect(mockFeedback).toHaveBeenCalledWith({ shop_id: 'shop-1', turn_id: null, kind: 'flag', reason: 'reply_draft' });
  expect(screen.getByRole('button', { name: 'Спасибо, мы проверим' })).toBeTruthy();
});
