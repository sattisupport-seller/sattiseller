import { interpolate, translate } from './index';
import { kk } from './kk';
import { ru } from './ru';

describe('тексты', () => {
  it('подстановка переменных', () => {
    expect(interpolate('Магазин «{name}»', { name: 'Демо' })).toBe('Магазин «Демо»');
    expect(interpolate('Привет, {who}', {})).toBe('Привет, {who}');
  });

  it('перевод по пути ключа и откат к ключу при отсутствии', () => {
    expect(translate('ru', 'overview.title')).toBe('Обзор');
    expect(translate('kk', 'overview.title')).toBe('Шолу');
    expect(translate('ru', 'no.such.key' as never)).toBe('no.such.key');
  });

  it('казахский словарь содержит те же ключи, что и русский', () => {
    const keys = (o: Record<string, unknown>, p = ''): string[] =>
      Object.entries(o).flatMap(([k, v]) =>
        typeof v === 'string' ? [`${p}${k}`] : keys(v as Record<string, unknown>, `${p}${k}.`),
      );
    expect(keys(kk as unknown as Record<string, unknown>).sort()).toEqual(keys(ru as unknown as Record<string, unknown>).sort());
  });
});
