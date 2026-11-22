import { flushAnalytics, setAnalyticsEnabled, trackEvent, _analyticsState } from './analytics';

const mockRequest = jest.fn(async () => ({}));
jest.mock('@/api/client', () => ({ request: (...args: unknown[]) => mockRequest(...(args as [])) }));

beforeEach(() => {
  mockRequest.mockClear();
  setAnalyticsEnabled(false);
});

test('выключено по умолчанию: события не копятся и не отправляются', async () => {
  trackEvent('paywall_shown');
  await flushAnalytics();
  expect(mockRequest).not.toHaveBeenCalled();
  expect(_analyticsState().queued).toBe(0);
});

test('двадцать событий уходят одним пакетом, без персональных данных', () => {
  setAnalyticsEnabled(true);
  for (let i = 0; i < 20; i += 1) trackEvent('paywall_shown');
  expect(mockRequest).toHaveBeenCalledTimes(1);
  const [path, opts] = mockRequest.mock.calls[0] as unknown as [string, { method: string; auth: boolean; body: { events: string[] } }];
  expect(path).toBe('/analytics/batch');
  expect(opts.method).toBe('POST');
  expect(opts.auth).toBe(false);
  expect(opts.body).toEqual({ events: Array(20).fill('paywall_shown') });
  expect(Object.keys(opts.body)).toEqual(['events']);  // только список имён, без других полей
  setAnalyticsEnabled(false);
});

test('остаток отправляется по запросу, пустая очередь не отправляет ничего', async () => {
  setAnalyticsEnabled(true);
  trackEvent('restore_tapped');
  await flushAnalytics();
  expect(mockRequest).toHaveBeenCalledTimes(1);
  await flushAnalytics();
  expect(mockRequest).toHaveBeenCalledTimes(1);
  setAnalyticsEnabled(false);
});

test('ошибка сети не ломает приложение и не возвращает события в очередь', async () => {
  setAnalyticsEnabled(true);
  mockRequest.mockRejectedValueOnce(new Error('network'));
  trackEvent('lock_screen_shown');
  await expect(flushAnalytics()).resolves.toBeUndefined();
  expect(_analyticsState().queued).toBe(0);
  setAnalyticsEnabled(false);
});
