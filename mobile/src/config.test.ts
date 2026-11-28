// QA-09: адрес сервера в релизной сборке проверяется.
import { apiUrlFromHostUri, checkApiUrl } from './config';

test('в разработке любой адрес допустим (localhost, IP в локальной сети)', () => {
  expect(checkApiUrl('http://localhost:8000/v1', true)).toBe('http://localhost:8000/v1');
  expect(checkApiUrl('http://192.168.0.10:8000/v1', true)).toBe('http://192.168.0.10:8000/v1');
});

test('в релизной сборке http и localhost отклоняются', () => {
  expect(() => checkApiUrl('http://localhost:8000/v1', false)).toThrow('https://');
  expect(() => checkApiUrl('http://satti.example.invalid/v1', false)).toThrow('https://');
});

test('в релизной сборке адрес-заглушка отклоняется', () => {
  expect(() => checkApiUrl('https://REPLACE-WITH-PRODUCTION-SERVER/v1', false)).toThrow('заглушка');
});

test('в релизной сборке https-адрес проходит', () => {
  expect(checkApiUrl('https://api.satti.example.invalid/v1', false)).toBe('https://api.satti.example.invalid/v1');
});

test('К-33 А0: адрес сервера из адреса Metro — тот же компьютер, порт 8000', () => {
  expect(apiUrlFromHostUri('172.20.10.2:8081')).toBe('http://172.20.10.2:8000/v1');
  expect(apiUrlFromHostUri('exp://192.168.0.5:8081/--/')).toBe('http://192.168.0.5:8000/v1');
  expect(apiUrlFromHostUri('172.20.10.2')).toBe('http://172.20.10.2:8000/v1');
  expect(apiUrlFromHostUri(null)).toBeNull();
  expect(apiUrlFromHostUri('')).toBeNull();
});
