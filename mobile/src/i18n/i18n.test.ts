import { interpolate, translate } from './index';

describe('тексты', () => {
  it('подстановка переменных', () => {
    expect(interpolate('Магазин «{name}»', { name: 'Демо' })).toBe('Магазин «Демо»');
    expect(interpolate('Привет, {who}', {})).toBe('Привет, {who}');
  });

  it('перевод по пути ключа и откат к ключу при отсутствии', () => {
    expect(translate('ru', 'overview.title')).toBe('Обзор');
    expect(translate('ru', 'no.such.key' as never)).toBe('no.such.key');
  });
});
