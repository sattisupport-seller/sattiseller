// 22.11: тесты экрана «Склад» (инвентаризация 0, приход только больше нуля) и экрана согласия на ИИ (Apple 5.1.2(i)).
import { fireEvent, render, screen, waitFor } from '@testing-library/react-native';

import AssistantScreen from '@/app/(tabs)/assistant';
import StockScreen from '@/app/stock';

const mockInventory = jest.fn(async () => undefined);
const mockReceipt = jest.fn(async () => undefined);
const mockConsent = jest.fn(async () => undefined);

jest.mock('expo-haptics', () => ({ selectionAsync: jest.fn(() => Promise.resolve()) }));

jest.mock('expo-router', () => ({
  useRouter: () => ({ push: jest.fn(), back: jest.fn(), replace: jest.fn() }),
  useLocalSearchParams: () => ({}),
  Stack: { Screen: () => null },
}));

jest.mock('@/session/SessionProvider', () => ({
  useSession: () => ({ shopId: 'shop-1', isDemo: true, locale: 'ru' }),
}));

jest.mock('@/components/ui/Overlays', () => ({
  ...jest.requireActual('@/components/ui/Overlays'),
  useToast: () => ({ show: jest.fn() }),
}));

jest.mock('@/api/hooks', () => {
  const noop = () => ({ data: undefined, isPending: false, mutate: jest.fn(), mutateAsync: jest.fn() });
  return {
    useStockList: () => ({
      data: { items: [{ productId: 'p1', sku: 'D007', name: 'Термокружка', current: 2, baseQty: 2, soldSince: 0,
        returnedSince: 0, avgDaily: 0.5, daysLeft: 4, level: 't3', delisted: false }] },
    }),
    useStockAlerts: () => ({ data: { items: [], endingSoon: [] } }),
    useProducts: () => ({ data: { pages: [{ items: [{ product_id: 'p1', sku: 'D007', name: 'Термокружка' }] }] } }),
    useStockMutations: () => ({
      inventory: { mutateAsync: mockInventory, isPending: false },
      receipt: { mutateAsync: mockReceipt, isPending: false },
      delist: { mutateAsync: jest.fn(), isPending: false },
      relist: { mutate: jest.fn(), isPending: false },
    }),
    useAIQuota: () => ({ data: { remaining: 20, limit: 30, consent_active: false, consent_version: null } }),
    useAIConsent: () => ({ mutateAsync: mockConsent, isPending: false }),
    useAsk: () => ({ mutateAsync: jest.fn(), isPending: false }),
    useFeedback: () => ({ mutate: jest.fn() }),
    useConversations: () => ({ data: { items: [] } }),
    useDeleteConversation: noop,
    useAppConfig: () => ({ data: {} }),
  };
});

beforeEach(() => {
  mockInventory.mockClear();
  mockReceipt.mockClear();
  mockConsent.mockClear();
});

describe('склад: ввод остатка', () => {
  test('инвентаризация принимает 0 (товар закончился)', async () => {
    await render(<StockScreen />);
    await fireEvent.press(screen.getByRole('button', { name: 'Инвентаризация' }));
    await fireEvent.changeText(await screen.findByLabelText('Количество, шт.'), '0');
    await fireEvent.press(screen.getByRole('button', { name: 'Сохранить' }));
    await waitFor(() => expect(mockInventory).toHaveBeenCalledWith({ productId: 'p1', qty: 0 }));
  });

  test('приход принимает только больше нуля', async () => {
    await render(<StockScreen />);
    await fireEvent.press(screen.getByRole('button', { name: 'Приход' }));
    await fireEvent.changeText(await screen.findByLabelText('Количество, шт.'), '0');
    await fireEvent.press(screen.getByRole('button', { name: 'Сохранить' }));
    expect(mockReceipt).not.toHaveBeenCalled();
    expect(await screen.findByText('Введите целое число больше нуля')).toBeTruthy();
  });
});

describe('согласие на ИИ (экран помощника)', () => {
  test('без согласия перед первым вопросом показывается экран с получателем данных и кнопками', async () => {
    await render(<AssistantScreen />);
    await fireEvent.changeText(await screen.findByLabelText('Спросите о магазине…'), 'Сколько прибыли за неделю?');
    await fireEvent.press(screen.getByRole('button', { name: 'Применить' }));
    expect(await screen.findByText('Помощник использует ИИ')).toBeTruthy();
    expect(screen.getByText(/Anthropic \(США\)/)).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Разрешить' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Не сейчас' })).toBeTruthy();
    await fireEvent.press(screen.getByRole('button', { name: 'Разрешить' }));
    await waitFor(() => expect(mockConsent).toHaveBeenCalledWith(true));
  });
});
