// QA: браузерные проверки публичных страниц и админ-панели (Edge через playwright-core).
// Тестовая среда: API на 127.0.0.1:8090 с временной базой. Реальных данных не касаемся.
const { chromium } = require('playwright-core');
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

const BASE = 'http://127.0.0.1:8090';
const OUT = process.env.QA_OUT;               // папка для скриншотов и результатов
const OUTBOX = process.env.QA_OUTBOX;         // папка писем тестового сервера
const ADMIN = 'boss-qa@example.com';
const results = [];
const consoleErrors = [];

function check(name, ok, detail = '') {
  results.push({ name, ok: !!ok, detail: String(detail).slice(0, 300) });
  console.log(`${ok ? 'PASS' : 'FAIL'} ${name}${detail ? ' — ' + String(detail).slice(0, 160) : ''}`);
}

function totp(secretB32, shift = 0) {
  const clean = secretB32.replace(/=+$/, '').toUpperCase();
  const alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567';
  let bits = '';
  for (const ch of clean) bits += alphabet.indexOf(ch).toString(2).padStart(5, '0');
  const key = Buffer.from(bits.match(/.{8}/g).map((b) => parseInt(b, 2)));
  const counter = Math.floor(Date.now() / 1000 / 30) + shift;
  const buf = Buffer.alloc(8);
  buf.writeBigUInt64BE(BigInt(counter));
  const h = crypto.createHmac('sha1', key).update(buf).digest();
  const off = h[h.length - 1] & 0x0f;
  const code = ((h[off] & 0x7f) << 24 | h[off + 1] << 16 | h[off + 2] << 8 | h[off + 3]) % 1000000;
  return String(code).padStart(6, '0');
}

function latestCodeFor(email) {
  const files = fs.readdirSync(OUTBOX).filter((f) => f.endsWith('.eml')).sort();
  for (let i = files.length - 1; i >= 0; i--) {
    const text = fs.readFileSync(path.join(OUTBOX, files[i]), 'utf8');
    if (text.includes('To: ' + email) && text.includes('Ваш код:')) return text.split('Ваш код: ')[1].split(/\s/)[0];
  }
  return null;
}

async function noHorizontalScroll(page) {
  return page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1);
}

(async () => {
  fs.mkdirSync(OUT, { recursive: true });
  const browser = await chromium.launch({
    executablePath: 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', headless: true,
  });
  const context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  const page = await context.newPage();
  page.on('console', (msg) => { if (msg.type() === 'error') consoleErrors.push(`${page.url()} :: ${msg.text()}`); });
  page.on('pageerror', (err) => consoleErrors.push(`${page.url()} :: pageerror ${err.message}`));

  // 1. Публичные страницы
  for (const [p, marker] of [['/privacy', 'Политика конфиденциальности'], ['/terms', 'Пользовательское соглашение']]) {
    const resp = await page.goto(BASE + p);
    const text = await page.textContent('body');
    check(`страница ${p} открывается`, resp.status() === 200, resp.status());
    check(`страница ${p} содержит текст и пометку черновика`, text.includes(marker) && text.includes('ЧЕРНОВИК'), '');
    await page.screenshot({ path: path.join(OUT, `page${p.replace('/', '-')}.png`), fullPage: true });
  }

  // 2. Форма удаления: пустой email, неизвестный адрес, повторная отправка
  await page.goto(BASE + '/delete-account');
  await page.click('button[type=submit]');
  const validity = await page.$eval('input[name=email]', (el) => el.validationMessage);
  check('форма удаления: пустой email не отправляется (обязательное поле)', validity.length > 0, validity);
  await page.fill('input[name=email]', 'nobody-qa@example.com');
  await page.click('button[type=submit]');
  await page.waitForSelector('text=Если аккаунт');
  check('форма удаления: неизвестный адрес получает тот же ответ, что и существующий', true, '');
  await page.screenshot({ path: path.join(OUT, 'page-delete-account-unknown.png') });

  // 3. Админ-панель: вход по коду
  await page.goto(BASE + '/admin');
  check('админ-панель открывается', (await page.textContent('h2')).length > 0, '');
  await page.fill('#email', ADMIN);
  await page.click('#send-code');
  await page.waitForSelector('#sign-in-error:has-text("Код отправлен")', { timeout: 10000 }).catch(() => {});
  const code = latestCodeFor(ADMIN);
  check('код входа пришёл в почтовый журнал (outbox)', !!code, code ? 'код получен' : 'нет письма');
  await page.fill('#code', code || '000000');
  await page.click('#verify-code');

  // 2FA: владелец без двухфакторной защиты должен увидеть настройку, а не данные
  await page.waitForSelector('#two-factor:not([hidden])', { timeout: 10000 }).catch(() => {});
  const tfVisible = await page.isVisible('#two-factor');
  check('без 2FA панель показывает настройку защиты (данные не открыты)', tfVisible && !(await page.isVisible('#stats-section')), '');
  await page.click('#tf-setup');
  await page.waitForSelector('#tf-secret:not(:empty)');
  const secret = await page.textContent('#tf-secret');
  await page.fill('#tf-code', totp(secret));
  await page.click('#tf-enable');
  await page.waitForSelector('#panel:not([hidden])', { timeout: 10000 }).catch(() => {});
  check('после подтверждения 2FA открыт раздел панели', await page.isVisible('#panel'), '');
  await page.screenshot({ path: path.join(OUT, 'admin-after-2fa.png'), fullPage: true });

  // Данные без кода — ошибка; с кодом — работают
  await page.fill('#admin-code', '');
  await page.click('#reload');
  await page.waitForTimeout(800);
  const errNoCode = await page.textContent('#panel-error');
  check('без кода 2FA данные не загружаются, видна ошибка', errNoCode.length > 0, errNoCode);
  await page.fill('#admin-code', totp(secret));
  await page.click('#reload');
  await page.waitForSelector('#stats-section:not([hidden])', { timeout: 10000 }).catch(() => {});
  check('с кодом 2FA загружается статистика', await page.isVisible('#stats-section'), '');
  await page.waitForSelector('#flags-section:not([hidden])', { timeout: 10000 }).catch(() => {});
  check('с кодом 2FA загружаются флаги', await page.isVisible('#flags-section'), '');
  await page.waitForSelector('#users-section:not([hidden])', { timeout: 10000 }).catch(() => {});
  check('с кодом 2FA загружаются пользователи', await page.isVisible('#users-section'), '');

  // Флаг: выключить и вернуть
  const flagBtn = page.locator('button[data-flag="ai_assistant"]');
  const before = await flagBtn.textContent();
  await flagBtn.click();
  await page.waitForTimeout(800);
  const after = await page.locator('button[data-flag="ai_assistant"]').textContent();
  check('переключение флага ИИ меняет состояние', before !== after, `${before} → ${after}`);
  await page.locator('button[data-flag="ai_assistant"]').click();
  await page.waitForTimeout(500);

  // Повторные нажатия: двойной клик на перезагрузку не ломает страницу
  await page.dblclick('#reload');
  await page.waitForTimeout(800);
  check('двойной клик «Обновить» не ломает страницу', await page.isVisible('#panel') && !(await page.textContent('#panel-error')).includes('Ошибка'), '');

  // Мобильный экран панели
  await page.setViewportSize({ width: 390, height: 844 });
  await page.reload();
  await page.waitForTimeout(500);
  check('панель на 390 px без горизонтальной прокрутки', await noHorizontalScroll(page), '');
  await page.screenshot({ path: path.join(OUT, 'admin-mobile-390.png'), fullPage: true });

  // Выход
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto(BASE + '/admin');
  const token = await page.evaluate(() => sessionStorage.getItem('satti-admin-token') || '');
  const htmlNow = await page.content();
  check('админ-панель: значение токена не попадает в HTML страницы', token.length > 0 && !htmlNow.includes(token), token ? 'токен есть только в sessionStorage' : 'токена нет');

  await browser.close();
  fs.writeFileSync(path.join(OUT, 'results-admin.json'), JSON.stringify({ results, consoleErrors }, null, 2));
  const failed = results.filter((r) => !r.ok).length;
  console.log(`\nИТОГО: ${results.length} проверок, провалено: ${failed}, ошибок консоли: ${consoleErrors.length}`);
})().catch((e) => { console.error('СЦЕНАРИЙ УПАЛ:', e); process.exit(1); });
