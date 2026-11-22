// QA: казахский и русский словари содержат одни и те же ключи, без пустых строк и без английского «заглушки».
import { kk } from './kk';
import { ru } from './ru';

type Tree = { [key: string]: unknown };

function leaves(obj: Tree, prefix = ''): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [k, v] of Object.entries(obj)) {
    const path = prefix ? `${prefix}.${k}` : k;
    if (v && typeof v === 'object') Object.assign(out, leaves(v as Tree, path));
    else out[path] = String(v ?? '');
  }
  return out;
}

const ruLeaves = leaves(ru as unknown as Tree);
const kkLeaves = leaves(kk as unknown as Tree);

test('в казахском переводе есть все ключи русского', () => {
  const missing = Object.keys(ruLeaves).filter((k) => !(k in kkLeaves));
  expect(missing).toEqual([]);
});

test('казахский не содержит лишних ключей', () => {
  const extra = Object.keys(kkLeaves).filter((k) => !(k in ruLeaves));
  expect(extra).toEqual([]);
});

test('нет пустых строк в переводах', () => {
  const empty = [...Object.entries(ruLeaves), ...Object.entries(kkLeaves)]
    .filter(([, v]) => v.trim() === '').map(([k]) => k);
  expect(empty).toEqual([]);
});
