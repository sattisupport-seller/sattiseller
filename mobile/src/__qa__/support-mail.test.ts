// К-35 п.4: письмо в поддержку — на satti.support@gmail.com, тема и в тексте номер продавца и версия приложения.
import { SUPPORT_EMAIL, supportMailto } from '@/config';

test('адрес, тема, номер продавца и версия', () => {
  expect(SUPPORT_EMAIL).toBe('satti.support@gmail.com');
  const url = supportMailto('17385187', '1.0.0 (5)');
  expect(url.startsWith('mailto:satti.support@gmail.com?subject=')).toBe(true);
  const params = new URLSearchParams(url.split('?')[1]);
  expect(params.get('subject')).toBe('Satti Seller — обращение');
  expect(params.get('body')).toContain('Номер продавца: 17385187');
  expect(params.get('body')).toContain('Версия приложения: 1.0.0 (5)');
});
