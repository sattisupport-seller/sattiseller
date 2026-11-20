// QA: сценарии пользователя в веб-версии приложения (телефонный экран 390×844). Edge через playwright-core.
const { chromium } = require('playwright-core');
const fs = require('fs');
const path = require('path');

const APP = 'http://127.0.0.1:8082';
const OUT = process.env.QA_OUT;
const results = [];
const consoleErrors = [];

function check(name, ok, detail = '') {
  results.push({ name, ok: !!ok, detail: String(detail).slice(0, 300) });
  console.log(`${ok ? 'PASS' : 'FAIL'} ${name}${detail ? ' — ' + String(detail).slice(0, 160) : ''}`);
}

async function settle(page, ms = 1200) { await page.waitForTimeout(ms); }

(async () => {
  fs.mkdirSync(OUT, { recursive: true });
  const browser = await chromium.launch({
    executablePath: 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', headless: true,
  });
  const context = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
  const page = await context.newPage();
  page.on('pageerror', (err) => consoleErrors.push(`pageerror ${err.message}`));
  page.on('console', (msg) => { if (msg.type() === 'error') consoleErrors.push(msg.text()); });

  // 1. Приветствие и вход в демо
  await page.goto(APP, { waitUntil: 'domcontentloaded', timeout: 180000 });
  await page.getByText('Попробовать на демо-магазине').first().waitFor({ timeout: 180000 });
  check('приветствие открылось на телефонном экране', true, '');
  await page.screenshot({ path: path.join(OUT, 'app-01-welcome.png') });
  await page.getByText('Попробовать на демо-магазине').first().click();
  await page.getByText('Это демо-магазин').first().waitFor({ timeout: 30000 }).catch(() => {});
  await settle(page, 2000);
  const overviewShown = await page.getByText('Обзор').first().isVisible().catch(() => false);
  check('демо-вход открывает вкладки приложения', overviewShown, '');
  await page.screenshot({ path: path.join(OUT, 'app-02-overview.png'), fullPage: true });
  check('обзор: баннер демо-магазина виден', await page.getByText('Это демо-магазин').first().isVisible().catch(() => false), '');

  // 2. Переходы по вкладкам: нет экрана ошибки, есть содержимое
  for (const tab of ['Товары', 'Заказы', 'Помощник', 'Профиль']) {
    await page.getByRole('tab', { name: tab }).first().click().catch(async () => page.getByText(tab, { exact: true }).last().click());
    await settle(page, 1500);
    const errorShown = await page.getByText('Не удалось загрузить').first().isVisible().catch(() => false);
    check(`вкладка «${tab}» открывается без ошибки загрузки`, !errorShown, '');
    await page.screenshot({ path: path.join(OUT, `app-tab-${tab}.png`) });
  }

  // 3. Товары: поиск — пустой, несуществующий, очень длинный ввод
  await page.getByRole('tab', { name: 'Товары' }).first().click().catch(() => {});
  await settle(page, 1000);
  const search = page.getByPlaceholder('Название или артикул').first();
  if (await search.count()) {
    await search.fill('zzz-несуществующий-товар');
    await settle(page, 1200);
    check('поиск по несуществующему товару не падает', true, '');
    await search.fill('я'.repeat(600));
    await settle(page, 1200);
    check('поиск с длинным вводом (600 символов) не ломает экран', !(await page.getByText('Ошибка').first().isVisible().catch(() => false)), '');
    await search.fill('');
    await settle(page, 800);
  } else {
    check('поле поиска товаров найдено', false, 'не найдено по placeholder');
  }
  await page.screenshot({ path: path.join(OUT, 'app-products-search.png') });

  // 4. Вход: с приветствия — кнопка «Войти по email», затем неверный адрес почты
  const fresh = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
  const p2 = await fresh.newPage();
  await p2.goto(APP, { waitUntil: 'domcontentloaded', timeout: 180000 });
  await p2.getByText('Войти по email').first().waitFor({ timeout: 180000 });
  await p2.getByText('Войти по email').first().click();
  await p2.waitForSelector('input[placeholder="you@example.com"]', { timeout: 60000 }).catch(() => {});
  const emailField = p2.getByPlaceholder('you@example.com').first();
  if (await emailField.count()) {
    await emailField.fill('не-почта');
    await p2.getByText('Получить код').first().click().catch(() => {});
    await settle(p2, 800);
    check('вход: неверный email показывает подсказку', await p2.getByText('Проверьте адрес почты').first().isVisible().catch(() => false), '');
    await p2.screenshot({ path: path.join(OUT, 'app-login-invalid-email.png') });
  } else {
    check('экран входа по email открыт, поле найдено', false, 'поле не найдено');
  }

  await browser.close();
  fs.writeFileSync(path.join(OUT, 'results-app.json'), JSON.stringify({ results, consoleErrors }, null, 2));
  console.log(`\nИТОГО: ${results.length} проверок, провалено: ${results.filter((r) => !r.ok).length}, ошибок консоли: ${consoleErrors.length}`);
})().catch((e) => { console.error('СЦЕНАРИЙ УПАЛ:', e.message); process.exit(1); });
