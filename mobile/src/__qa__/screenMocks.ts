// Общие моки для тестов экранов (22.11): хуки API возвращают пустые результаты, чтобы экран отрисовался.
// Переопределения передаются явно в конкретном тесте.
export function hookResult(extra: Record<string, unknown> = {}) {
  return {
    data: undefined,
    isPending: false,
    isLoading: false,
    isError: false,
    error: null,
    mutate: jest.fn(),
    mutateAsync: jest.fn(async () => ({})),
    refetch: jest.fn(),
    fetchNextPage: jest.fn(),
    hasNextPage: false,
    isFetchingNextPage: false,
    ...extra,
  };
}

export function hooksMock(overrides: Record<string, unknown> = {}) {
  return new Proxy(overrides, {
    get: (target, key) => {
      if (typeof key !== 'string' || key === '__esModule' || key === 'then') return undefined;
      if (key in target) return target[key];
      return () => hookResult();
    },
  });
}
