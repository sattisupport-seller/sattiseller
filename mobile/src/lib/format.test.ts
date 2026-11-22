import {
  accessibleMoney,
  formatCount,
  formatDayLabel,
  formatMoney,
  formatMoneyShort,
  formatPercentBp,
  formatPeriodRange,
  formatTime,
  isMoneyInput,
  tiynToTengeRounded,
} from './format';

const NBSP = ' ';
const MINUS = '−';

describe('деньги', () => {
  it('целые тенге с неразрывными пробелами', () => {
    expect(formatMoney(124530000)).toBe(`1${NBSP}245${NBSP}300${NBSP}₸`);
    expect(formatMoney(0)).toBe(`0${NBSP}₸`);
  });

  it('знак минус — U+2212, плюс — только при sign=auto', () => {
    expect(formatMoney(-860000)).toBe(`${MINUS}8${NBSP}600${NBSP}₸`);
    expect(formatMoney(9620000, 'auto')).toBe(`+96${NBSP}200${NBSP}₸`);
    expect(formatMoney(9620000)).toBe(`96${NBSP}200${NBSP}₸`);
  });

  it('округление половины вверх от нуля: как в Excel (R001–R003 из ТЗ)', () => {
    expect(tiynToTengeRounded(42407)).toBe(424); // R001 на экране 424 ₸
    expect(tiynToTengeRounded(42450)).toBe(425); // R002 — 425 ₸
    expect(tiynToTengeRounded(-42450)).toBe(-425); // R003 — −425 ₸
  });

  it('пустое значение — тире', () => {
    expect(formatMoney(null)).toBe('—');
    expect(formatMoney(undefined)).toBe('—');
  });

  it('сокращения: KPI от миллиона — два знака, списки — от 10 млн один знак', () => {
    expect(formatMoneyShort(124530000, 'kpi')).toBe(`1,25${NBSP}млн${NBSP}₸`);
    expect(formatMoneyShort(9999900, 'list')).toBe(`99${NBSP}999${NBSP}₸`);
    expect(formatMoneyShort(1_240_000_000, 'list')).toBe(`12,4${NBSP}млн${NBSP}₸`);
  });

  it('голосовое описание без разряженного ввода', () => {
    expect(accessibleMoney(-860000)).toBe('минус 8 600 тенге');
  });
});

describe('проценты', () => {
  it('из базисных пунктов с одним знаком', () => {
    expect(formatPercentBp(2041)).toBe('20,4%');
    expect(formatPercentBp(-1280, 'auto')).toBe(`${MINUS}12,8%`);
    expect(formatPercentBp(420, 'auto')).toBe('+4,2%');
    expect(formatPercentBp(null)).toBe('—');
  });
});

describe('счётчики', () => {
  it('склонение заказов', () => {
    expect(formatCount(1, 'orders')).toBe('1 заказ');
    expect(formatCount(3, 'orders')).toBe('3 заказа');
    expect(formatCount(64, 'orders')).toBe('64 заказа');
    expect(formatCount(11, 'orders')).toBe('11 заказов');
    expect(formatCount(22, 'orders')).toBe('22 заказа');
  });

  it('казахский — без изменения существительного', () => {
    expect(formatCount(64, 'orders', 'ru')).toBe('64 заказа');
  });

  it('штуки', () => {
    expect(formatCount(14, 'units')).toBe('14 шт.');
  });
});

describe('даты', () => {
  const today = '2026-11-19';
  it('сегодня, вчера, дата', () => {
    expect(formatDayLabel('2026-11-19', today)).toBe('сегодня');
    expect(formatDayLabel('2026-11-18', today, 'ru', '2026-11-18')).toBe('вчера');
    expect(formatDayLabel('2026-11-17', today)).toBe('17 нояб.');
    expect(formatDayLabel('2025-11-17', today)).toBe('17 нояб. 2025');
  });

  it('диапазоны периодов', () => {
    expect(formatPeriodRange('2026-11-06', '2026-11-19')).toBe('6–19 нояб.');
    expect(formatPeriodRange('2026-10-23', '2026-11-05')).toBe('23 окт. – 5 нояб.');
  });

  it('время 24-часовое', () => {
    expect(formatTime('2026-11-19T15:40:00+05:00')).toBe('15:40');
  });
});

describe('ввод денег', () => {
  it('принимает цифры, пробелы, одну запятую или точку и до двух знаков', () => {
    expect(isMoneyInput('2 800')).toBe(true);
    expect(isMoneyInput('1200,5')).toBe(true);
    expect(isMoneyInput('1200,505')).toBe(false);
    expect(isMoneyInput('12a')).toBe(false);
  });
});
