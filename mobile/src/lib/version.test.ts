import { isBelow } from './version';

describe('сравнение версий приложения', () => {
  it('ниже минимальной — обновление нужно', () => {
    expect(isBelow('1.0.0', '1.0.1')).toBe(true);
    expect(isBelow('1.2.9', '2.0.0')).toBe(true);
  });
  it('равна или выше — без обновления', () => {
    expect(isBelow('1.0.0', '1.0.0')).toBe(false);
    expect(isBelow('1.10.0', '1.9.0')).toBe(false);
    expect(isBelow('1.0', '1.0.0')).toBe(false);
  });
});
