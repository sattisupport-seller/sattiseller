// Таблица казахских строк на проверку носителем языка (spec-2.1, задача 17).
//
//   node scripts/kk-review.mjs export   — пишет docs/i18n-kk-review.csv (ключ, экран, русский, казахский, комментарий, статус)
//   node scripts/kk-review.mjs apply    — переносит исправления из CSV в src/i18n/kk.ts,
//                                         только строки со статусом «проверено» и заполненным казахским
//
// Только простые строки вида key: 'текст' (и key:\n  'текст'). Словари не выполняются, файлы читаются как текст.
import { readFileSync, writeFileSync, existsSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const RU = join(root, 'src/i18n/ru.ts');
const KK = join(root, 'src/i18n/kk.ts');
const CSV = join(root, '..', 'docs', 'i18n-kk-review.csv');

// Возвращает Map ключ -> { value, line } (строка файла с значением, индекс с нуля).
function parseDict(file) {
  const lines = readFileSync(file, 'utf8').split('\n');
  const map = new Map();
  const stack = [];
  let pendingKey = null;
  lines.forEach((raw, i) => {
    const line = raw.replace(/\r$/, '');
    const open = line.match(/^\s*(\w+): \{\s*$/);
    if (open) { stack.push(open[1]); return; }
    if (/^\s*\},?\s*$/.test(line)) { stack.pop(); return; }
    const one = line.match(/^\s*(\w+): '((?:[^'\\]|\\.)*)',?\s*$/);
    if (one) {
      map.set([...stack, one[1]].join('.'), { value: one[2], line: i });
      pendingKey = null;
      return;
    }
    const head = line.match(/^\s*(\w+):\s*$/);
    if (head) { pendingKey = head[1]; return; }
    if (pendingKey) {
      const cont = line.match(/^\s*'((?:[^'\\]|\\.)*)',?\s*$/);
      if (cont) map.set([...stack, pendingKey].join('.'), { value: cont[1], line: i });
      pendingKey = null;
    }
  });
  return { map, lines };
}

const csvCell = (s) => `"${String(s ?? '').replace(/"/g, '""')}"`;

function parseCsv(text) {
  const rows = [];
  let row = [], cell = '', q = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (q) {
      if (c === '"' && text[i + 1] === '"') { cell += '"'; i++; }
      else if (c === '"') q = false;
      else cell += c;
    } else if (c === '"') q = true;
    else if (c === ',') { row.push(cell); cell = ''; }
    else if (c === '\n') { row.push(cell); rows.push(row); row = []; cell = ''; }
    else if (c !== '\r') cell += c;
  }
  if (cell || row.length) { row.push(cell); rows.push(row); }
  return rows;
}

function exportCsv() {
  const ru = parseDict(RU).map;
  const old = existsSync(CSV) ? parseCsv(readFileSync(CSV, 'utf8')) : [];
  // Сохраняем уже заполненные комментарии и статусы из прошлой выгрузки.
  const prev = new Map(old.slice(1).map((r) => [r[0], { comment: r[4] ?? '', status: r[5] ?? '' }]));
  const kk = parseDict(KK).map;
  const out = ['ключ,экран,русский,казахский,комментарий,статус'];
  for (const [key, { value: ruValue }] of ru) {
    const kkValue = kk.get(key)?.value ?? '';
    const p = prev.get(key) ?? { comment: '', status: 'на проверке' };
    const screen = key.split('.')[0];
    out.push([key, screen, ruValue, kkValue, p.comment, p.status].map(csvCell).join(','));
  }
  writeFileSync(CSV, '﻿' + out.join('\n') + '\n', 'utf8');
  console.log(`Записано строк: ${out.length - 1} → ${CSV}`);
}

function applyCsv() {
  const rows = parseCsv(readFileSync(CSV, 'utf8').replace(/^﻿/, ''));
  const { map, lines } = parseDict(KK);
  let changed = 0;
  for (const [key, , , kkValue, , status] of rows.slice(1)) {
    if (status !== 'проверено' || !kkValue) continue;
    const entry = map.get(key);
    if (!entry || entry.value === kkValue) continue;
    const escaped = kkValue.replace(/\\/g, '\\\\').replace(/'/g, "\\'");
    lines[entry.line] = lines[entry.line].replace(/'((?:[^'\\]|\\.)*)'/, `'${escaped}'`);
    changed++;
  }
  writeFileSync(KK, lines.join('\n'), 'utf8');
  console.log(`Исправлено строк: ${changed}`);
}

const mode = process.argv[2];
if (mode === 'export') exportCsv();
else if (mode === 'apply') applyCsv();
else console.log('Использование: node scripts/kk-review.mjs export|apply');
