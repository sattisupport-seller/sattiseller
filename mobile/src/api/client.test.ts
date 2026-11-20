// AUD-04: параллельные запросы с истекшим токеном должны обновить сессию один раз.
import { deleteItem } from '@/lib/storage';

import { ApiError, loadStoredSession, request, saveTokens, setSessionLostHandler } from './client';

jest.mock('@/config', () => ({ API_URL: 'http://test.local/v1' }));

const mockStore = new Map<string, string>();
jest.mock('@/lib/storage', () => ({
  getItem: jest.fn(async (k: string) => mockStore.get(k) ?? null),
  setItem: jest.fn(async (k: string, v: string) => {
    mockStore.set(k, v);
  }),
  deleteItem: jest.fn(async (k: string) => {
    mockStore.delete(k);
  }),
}));

function json(status: number, body: unknown) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
    text: async () => JSON.stringify(body),
    arrayBuffer: async () => new ArrayBuffer(0),
  } as unknown as Response;
}

type Handler = (url: string, init: RequestInit) => Response | Promise<Response>;
let handler: Handler;

beforeEach(() => {
  jest.clearAllMocks();
  mockStore.clear();
  (globalThis as { fetch?: unknown }).fetch = jest.fn((url: string, init: RequestInit) => handler(url, init));
  setSessionLostHandler(() => undefined);
});

async function setup() {
  await saveTokens('A1', 'R1');
  await loadStoredSession();
}

test('три параллельных запроса с истекшим токеном обновляют сессию один раз', async () => {
  await setup();
  let refreshCalls = 0;
  handler = async (url, init) => {
    if (url.endsWith('/auth/refresh')) {
      refreshCalls += 1;
      return json(200, { access_token: 'A2', refresh_token: 'R2' });
    }
    const auth = (init.headers as Record<string, string>).Authorization;
    if (auth === 'Bearer A1') return json(401, { error: { code: 'token_expired', message: 'x', error_id: '1' } });
    return json(200, { ok: true });
  };

  const results = await Promise.all([
    request<{ ok: boolean }>('/a'),
    request<{ ok: boolean }>('/b'),
    request<{ ok: boolean }>('/c'),
  ]);

  expect(results).toEqual([{ ok: true }, { ok: true }, { ok: true }]);
  expect(refreshCalls).toBe(1);
  expect(mockStore.get('satti.refresh')).toBe('R2');
});

test('сервер отказал в обновлении — выход из аккаунта', async () => {
  await setup();
  const lost = jest.fn();
  setSessionLostHandler(lost);
  handler = async (url) => {
    if (url.endsWith('/auth/refresh')) return json(401, { error: { code: 'unauthorized', message: 'x', error_id: '1' } });
    return json(401, { error: { code: 'token_expired', message: 'x', error_id: '1' } });
  };
  await expect(request('/a')).rejects.toMatchObject({ status: 401 });
  expect(lost).toHaveBeenCalledTimes(1);
  expect(mockStore.has('satti.refresh')).toBe(false);
});

test('сетевой сбой при обновлении не выкидывает пользователя', async () => {
  await setup();
  const lost = jest.fn();
  setSessionLostHandler(lost);
  handler = async (url) => {
    if (url.endsWith('/auth/refresh')) throw new TypeError('Network request failed');
    return json(401, { error: { code: 'token_expired', message: 'x', error_id: '1' } });
  };
  await expect(request('/a')).rejects.toBeInstanceOf(ApiError);
  expect(lost).not.toHaveBeenCalled();
  expect(mockStore.get('satti.refresh')).toBe('R1');
  expect(deleteItem).not.toHaveBeenCalledWith('satti.refresh');
});
