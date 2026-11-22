// Импорт затрат (1.11, 22.11): файл не XLSX/CSV отклоняется до загрузки; сопоставление без артикула и закупки не идёт дальше.
import { fireEvent, render, screen, waitFor } from '@testing-library/react-native';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

const mockPick = jest.fn(async () => ({ canceled: false, assets: [{ uri: 'file:///x.pdf', name: 'costs.pdf', mimeType: 'application/pdf' }] }));
const mockUpload = jest.fn(async (..._a: unknown[]) => ({ id: 'imp-1', mapping: { sku: null, purchase: null }, sample: [] }));

jest.mock('expo-haptics', () => ({ selectionAsync: jest.fn(() => Promise.resolve()) }));
jest.mock('expo-router', () => ({
  useRouter: () => ({ push: jest.fn(), back: jest.fn(), replace: jest.fn() }),
  useLocalSearchParams: () => ({}),
  Stack: { Screen: () => null },
}));
jest.mock('expo-file-system', () => ({ File: jest.fn(), Paths: { cache: '/tmp' } }));
jest.mock('expo-sharing', () => ({ shareAsync: jest.fn(), isAvailableAsync: jest.fn(async () => false) }));
jest.mock('expo-document-picker', () => ({ getDocumentAsync: mockPick }));
jest.mock('@/components/ui/Overlays', () => ({ ...jest.requireActual('@/components/ui/Overlays'), useToast: () => ({ show: jest.fn() }) }));
jest.mock('@/session/SessionProvider', () => ({ useSession: () => ({ shopId: 'shop-1', isDemo: true, locale: 'ru' }) }));
jest.mock('@/api/hooks', () => {
  const m = require('./screenMocks');
  return m.hooksMock({
    useImportUpload: () => m.hookResult({ mutateAsync: mockUpload }),
  });
});

const ImportScreen = require('@/app/import').default;

function renderImport() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}><ImportScreen /></QueryClientProvider>);
}

beforeEach(() => {
  mockPick.mockClear();
  mockUpload.mockClear();
});

test('файл не XLSX и не CSV отклоняется до загрузки', async () => {
  await renderImport();
  await fireEvent.press(screen.getByRole('button', { name: 'Выбрать файл' }));  // шаг 1 → шаг 2
  const pickBtns = await screen.findAllByRole('button', { name: 'Выбрать файл' });
  await fireEvent.press(pickBtns[pickBtns.length - 1]);
  expect(await screen.findByText('Выберите файл XLSX или CSV')).toBeTruthy();
  expect(mockUpload).not.toHaveBeenCalled();
});
