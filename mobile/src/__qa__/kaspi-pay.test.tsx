// К-33 Б1: «Сверка с Kaspi: совпало / расхождение N ₸ по M заказам» после выбора файла Kaspi Pay.
import { fireEvent, render, screen, waitFor } from '@testing-library/react-native';

const mockUpload = jest.fn();

jest.mock('expo-router', () => ({ Stack: { Screen: () => null }, useRouter: () => ({ push: jest.fn() }) }));
jest.mock('expo-document-picker', () => ({
  getDocumentAsync: jest.fn(() => Promise.resolve({ canceled: false, assets: [{ uri: 'file:///s.xlsx', name: 's.xlsx', mimeType: 'x' }] })),
}));
jest.mock('@/session/SessionProvider', () => ({ useSession: () => ({ shopId: 'shop-1', isDemo: false, locale: 'ru' }) }));
jest.mock('@/api/hooks', () => {
  const m = require('./screenMocks');
  return m.hooksMock({ useKaspiPayReport: () => m.hookResult({ mutateAsync: mockUpload }) });
});

const KaspiPayScreen = require('@/app/settings/kaspi-pay').default;

test('сверка: совпало, расхождение по заказам, строка расхождения', async () => {
  mockUpload.mockResolvedValue({
    rows: 4, bad_rows: [5], columns: {}, orders_in_file: 3, matched: 1, mismatch_orders: 1, mismatch_sum_minor: 10000,
    mismatches: [{ order_number: 'B-1', field: 'amount', satti_minor: 800000, kaspi_minor: 790000, diff_minor: -10000 }],
    missing_in_satti: ['X-9'], missing_in_satti_count: 1,
  });
  await render(<KaspiPayScreen />);
  await fireEvent.press(screen.getByRole('button', { name: 'Выбрать файл Kaspi Pay' }));
  await waitFor(() => expect(screen.getByText('Сверка с Kaspi: совпало заказов — 1; расхождение 100 ₸, заказов с расхождением — 1')).toBeTruthy());
  expect(screen.getByText('B-1 · сумма')).toBeTruthy();
  expect(screen.getByText(/Заказов в файле, которых нет в Satti: 1/)).toBeTruthy();
});
