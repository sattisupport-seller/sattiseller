// К-13 (22.11): интерфейс только на русском. Казахский словарь (kk.ts) оставлен в репозитории, но не подключён.
import { LOCALES } from './index';
import { ru } from './ru';

type Tree = { [key: string]: unknown };

function leaves(obj: Tree, prefix = ''): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [k, v] of Object.entries(obj)) {
    const p = prefix ? `${prefix}.${k}` : k;
    if (v && typeof v === 'object') Object.assign(out, leaves(v as Tree, p));
    else out[p] = String(v ?? '');
  }
  return out;
}

test('в русском словаре нет пустых строк', () => {
  const empty = Object.keys(leaves(ru as unknown as Tree)).filter((k) => leaves(ru as unknown as Tree)[k].trim() === '');
  expect(empty).toEqual([]);
});

test('подключён только русский язык интерфейса', () => {
  expect([...LOCALES]).toEqual(['ru']);
});
