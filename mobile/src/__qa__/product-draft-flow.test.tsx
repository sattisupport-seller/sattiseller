// Черновик карточки товара (1.11, 22.11): без фактов кнопка неактивна; с фактами черновик создаётся и показывается.
import { fireEvent, render, screen, waitFor } from '@testing-library/react-native';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

const mockDraft = jest.fn(async (..._a: unknown[]) => ({
  titles: ['Термокружка 450 мл'],
  description: 'Термокружка из нержавеющей стали.',
  characteristics: [{ name: 'Материал', value: 'нержавейка' }],
  warnings: [],
  generatedBy: 'ai',
}));

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
  return m.hooksMock({ useProductDraft: () => m.hookResult({ mutateAsync: mockDraft }) });
});

const ProductDraftScreen = require('@/app/assistant/product-draft').default;

function renderScreen() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}><ProductDraftScreen /></QueryClientProvider>);
}

beforeEach(() => mockDraft.mockClear());

test('без фактов о товаре черновик не создаётся', async () => {
  await renderScreen();
  await fireEvent.press(screen.getByRole('button', { name: 'Составить описание' }));
  expect(mockDraft).not.toHaveBeenCalled();
});

test('с фактами черновик создаётся и показывает название и описание', async () => {
  await renderScreen();
  await fireEvent.changeText(screen.getByLabelText('Факты о товаре'), 'Материал: нержавейка, 450 мл');
  await fireEvent.press(screen.getByRole('button', { name: 'Составить описание' }));
  await waitFor(() => expect(mockDraft).toHaveBeenCalledTimes(1));
  expect(await screen.findByText('Термокружка из нержавеющей стали.')).toBeTruthy();
  expect(screen.getByText('Термокружка 450 мл')).toBeTruthy();
});
