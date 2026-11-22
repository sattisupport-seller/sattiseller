// Импорт затрат (1.11, 22.11): файл не XLSX/CSV отклоняется до загрузки; сопоставление без артикула и закупки не идёт дальше.
import { fireEvent, render, screen, waitFor } from '@testing-library/react-native';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

const mockPick = jest.fn(async () => ({ canceled: false, assets: [{ uri: 'file:///x.pdf', name: 'costs.pdf', mimeType: 'application/pdf' }] }));
const mockPickXlsx = jest.fn(async () => ({ canceled: false, assets: [{ uri: 'file:///c.xlsx', name: 'costs.xlsx', mimeType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' }] }));
const mockUpload = jest.fn(async (..._a: unknown[]) => ({
  id: 'imp-1', filename: 'costs.xlsx', rows_total: 2, columns: ['Артикул', 'Закупка'],
  mapping: { sku: null, purchase: null, delivery_to_warehouse: null, packaging: null, other: null, effective_from: null },
  sample: [['D007', '2800']],
}));
const mockMapping = jest.fn(async (..._a: unknown[]) => ({}));

jest.mock('expo-haptics', () => ({ selectionAsync: jest.fn(() => Promise.resolve()) }));
jest.mock('expo-router', () => ({
  useRouter: () => ({ push: jest.fn(), back: jest.fn(), replace: jest.fn() }),
  useLocalSearchParams: () => ({}),
  Stack: { Screen: () => null },
}));
jest.mock('expo-file-system', () => ({ File: jest.fn(), Paths: { cache: '/tmp' } }));
jest.mock('expo-sharing', () => ({ shareAsync: jest.fn(), isAvailableAsync: jest.fn(async () => false) }));
jest.mock('expo-document-picker', () => ({ getDocumentAsync: (...a: unknown[]) => (globalThis as unknown as { __pick?: () => unknown }).__pick?.() ?? mockPick() }));
jest.mock('@/components/ui/Overlays', () => ({ ...jest.requireActual('@/components/ui/Overlays'), useToast: () => ({ show: jest.fn() }) }));
jest.mock('@/session/SessionProvider', () => ({ useSession: () => ({ shopId: 'shop-1', isDemo: true, locale: 'ru' }) }));
jest.mock('@/api/hooks', () => {
  const m = require('./screenMocks');
  return m.hooksMock({
    useImportUpload: () => m.hookResult({ mutateAsync: mockUpload }),
    useImportMapping: () => m.hookResult({ mutateAsync: mockMapping }),
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
  mockMapping.mockClear();
  (globalThis as unknown as { __pick?: unknown }).__pick = undefined;
});

test('файл не XLSX и не CSV отклоняется до загрузки', async () => {
  await renderImport();
  await fireEvent.press(screen.getByRole('button', { name: 'Выбрать файл' }));  // шаг 1 → шаг 2
  const pickBtns = await screen.findAllByRole('button', { name: 'Выбрать файл' });
  await fireEvent.press(pickBtns[pickBtns.length - 1]);
  expect(await screen.findByText('Выберите файл XLSX или CSV')).toBeTruthy();
  expect(mockUpload).not.toHaveBeenCalled();
});

async function goToMapping() {
  (globalThis as unknown as { __pick?: () => unknown }).__pick = mockPickXlsx;
  await renderImport();
  await fireEvent.press(screen.getByRole('button', { name: 'Выбрать файл' }));
  const pickBtns = await screen.findAllByRole('button', { name: 'Выбрать файл' });
  await fireEvent.press(pickBtns[pickBtns.length - 1]);
  await waitFor(() => expect(mockUpload).toHaveBeenCalledTimes(1));
  expect(await screen.findByText('Сопоставление колонок')).toBeTruthy();
}

test('без колонки закупки сопоставление не отправляется', async () => {
  await goToMapping();
  // строки полей идут в порядке: артикул, закупка…; в каждой строке свои кнопки колонок
  await fireEvent.press(screen.getAllByRole('button', { name: 'Артикул' })[0]);
  await fireEvent.press(screen.getByRole('button', { name: 'Далее' }));
  expect(await screen.findByText('Укажите колонки артикула и закупки')).toBeTruthy();
  expect(mockMapping).not.toHaveBeenCalled();
});

test('с колонками артикула и закупки сопоставление уходит на сервер', async () => {
  await goToMapping();
  await fireEvent.press(screen.getAllByRole('button', { name: 'Артикул' })[0]);
  await fireEvent.press(screen.getAllByRole('button', { name: 'Закупка' })[1]);
  await fireEvent.press(screen.getByRole('button', { name: 'Далее' }));
  await waitFor(() => expect(mockMapping).toHaveBeenCalledTimes(1));
  const args = mockMapping.mock.calls[0][0] as { importId: string; duplicates: string; mapping: { sku: string; purchase: string } };
  expect(args.importId).toBe('imp-1');
  expect(args.duplicates).toBe('skip');
  expect(args.mapping.sku).toBe('Артикул');
  expect(args.mapping.purchase).toBe('Закупка');
});
