// К-33 А5: главный экран языком денег — утечки маржи с итогом за месяц, порог доставки, защита от отмен.
import { render, screen } from '@testing-library/react-native';

jest.mock('expo-router', () => ({ useRouter: () => ({ push: jest.fn() }) }));
jest.mock('@/session/SessionProvider', () => ({ useSession: () => ({ shopId: 'shop-1', isDemo: false, locale: 'ru' }) }));
jest.mock('@/api/hooks', () => {
  const m = require('./screenMocks');
  return m.hooksMock({
    useMoneyInsights: () => m.hookResult({ data: {
      period: { from: '2026-10-30', to: '2026-11-28' }, vat_payer: false,
      leaks: { items: [{ product_id: 'p1', sku: 'D023', name: 'Термокружка', sold_qty: 3, avg_price_minor: 180000,
        unit_cost_minor: 190000, profit_minor: -197500, margin_bp: -3657, per_unit: { commission: 22500, delivery: 33333 },
        worst_rate_bp: 1300, worst_unit_profit_minor: -66733, min_price_minor: 256800 }],
        count: 1, losing_count: 1, month_loss_minor: 197500, near_zero_bp: 300 },
      threshold_hints: [{ product_id: 'p2', name: 'Power bank', price_minor: 520000, threshold_tenge: 5000,
        suggested_price_minor: 499000, gain_per_order_minor: 39625 }],
      cancel_protection: { protected_count: 2, protected: [], preview: false, orders_count: 117, sold_orders_count: 67,
        cancelled_count: 10, cancel_share_bp: 855, kaspi_limit_bp: 300, note: 'Kaspi считает только отмены по вине продавца.' },
      time_saving: { ai_card: true, reply_templates: true },
    } }),
  });
});

const { MoneyCards } = require('@/components/MoneyCards');

test('утечки маржи, порог доставки и отмены — языком денег', async () => {
  await render(<MoneyCards shopId="shop-1" />);
  expect(screen.getByText(/За месяц вы теряете 1\s975 ₸ на 1 товар/)).toBeTruthy();
  expect(screen.getByText(/без убытка — от 2\s568 ₸/)).toBeTruthy();
  expect(screen.getByText(/Power bank: 5\s200 ₸ → 4\s990 ₸ — на 396 ₸ больше с заказа/)).toBeTruthy();
  expect(screen.getByText(/Отмены за 30 дней: 8,6% \(10 из 117 заказов\), порог Kaspi — 3,0%/)).toBeTruthy();
  expect(screen.queryByText(/штраф/)).toBeNull();
}, 60_000);
