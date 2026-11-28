"use strict";
const API = "/v1";
const $ = (id) => document.getElementById(id);
let token = sessionStorage.getItem("satti-admin-token") || null;
let emailAddress = "";

function show(id, on) { $(id).hidden = !on; }
function esc(s) { return String(s ?? "").replace(/[&<>"']/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c])); }

// Сессия панели (30 минут) хранится только в памяти вкладки; код из приложения вводится один раз на сессию.
let adminSession = null;
async function ensureAdminSession() {
  if (adminSession) return;
  const r = await api("/admin/session", { method: "POST", body: { code: $("admin-code").value.trim() } });
  adminSession = r.admin_session;
  setTimeout(() => { adminSession = null; }, Math.max(0, r.expires_in - 30) * 1000);
}

async function api(path, { method = "GET", body, admin = false } = {}) {
  const headers = { "Content-Type": "application/json" };
  if (token) headers.Authorization = "Bearer " + token;
  if (admin) { await ensureAdminSession(); headers["X-Admin-Session"] = adminSession; }
  const res = await fetch(API + path, { method, headers, body: body ? JSON.stringify(body) : undefined });
  let data = null;
  try { data = await res.json(); } catch (_) { data = null; }
  if (!res.ok) {
    const code = data && data.error ? data.error.code : "http";
    if (code === "admin_session_required") adminSession = null;
    const msg = data && data.error ? data.error.message : "Ошибка " + res.status;
    const err = new Error(msg); err.code = code; err.status = res.status; throw err;
  }
  return data;
}

async function sendCode() {
  $("sign-in-error").textContent = "";
  emailAddress = $("email").value.trim().toLowerCase();
  try { await api("/auth/email/start", { method: "POST", body: { email: emailAddress } }); $("sign-in-error").textContent = "Код отправлен на почту."; }
  catch (e) { $("sign-in-error").textContent = e.message; }
}

async function verifyCode() {
  $("sign-in-error").textContent = "";
  try {
    const res = await api("/auth/email/verify", { method: "POST", body: { email: emailAddress, code: $("code").value.trim() } });
    token = res.access_token;
    sessionStorage.setItem("satti-admin-token", token);
    await afterSignIn();
  } catch (e) { $("sign-in-error").textContent = e.message; }
}

async function afterSignIn() {
  show("sign-in", false);
  show("logout", true);
  try {
    await api("/admin/stats", { admin: true });
    show("two-factor", false);
    show("panel", true);
    loadAll();
  } catch (e) {
    if (e.code === "two_factor_required") { show("two-factor", true); $("tf-text").textContent = "Включите двухфакторную защиту: создайте секрет и введите код из приложения-аутентификатора."; }
    else if (e.status === 404) { $("sign-in-error").textContent = "Панель недоступна для этого аккаунта."; show("sign-in", true); show("logout", true); }
    else if (e.code === "admin_code_invalid") { show("panel", true); $("panel-error").textContent = "Введите код двухфакторной защиты в поле выше."; }
    else { $("sign-in-error").textContent = e.message; show("sign-in", true); }
  }
}

async function setupTwoFactor() {
  $("tf-error").textContent = "";
  try { const r = await api("/admin/2fa/setup", { method: "POST" }); $("tf-secret").textContent = r.secret; }
  catch (e) { $("tf-error").textContent = e.message; }
}

async function enableTwoFactor() {
  $("tf-error").textContent = "";
  try { await api("/admin/2fa/enable", { method: "POST", body: { code: $("tf-code").value.trim() } }); show("two-factor", false); show("panel", true); loadAll(); }
  catch (e) { $("tf-error").textContent = e.message; }
}

async function loadStats() {
  const s = await api("/admin/stats", { admin: true });
  const labels = { users: "Пользователей", shops: "Магазинов", orders: "Заказов", ai_conversations: "Диалогов ИИ", ai_questions: "Вопросов ИИ", blocked_users: "Заблокировано" };
  $("stats").innerHTML = Object.entries(labels).map(([k, label]) => `<div class="kpi"><b>${esc(s[k])}</b>${esc(label)}</div>`).join("");
  show("stats-section", true);
}

async function loadFlags() {
  const f = await api("/admin/flags", { admin: true });
  const names = { kaspi_connection: "Подключение Kaspi", ai_assistant: "ИИ-помощник", subscription: "Подписка" };
  $("flags").innerHTML = Object.entries(f).map(([k, on]) =>
    `<tr><td>${esc(names[k] || k)}<div class="muted">${esc(k)}</div></td><td>${on ? "включён" : "выключен"}</td>` +
    `<td><button class="secondary" data-flag="${esc(k)}" data-on="${on ? 0 : 1}">${on ? "Выключить" : "Включить"}</button></td></tr>`).join("");
  show("flags-section", true);
}

async function loadUsers() {
  const fb = await api("/admin/ai-feedback", { admin: true });
  $("ai-feedback").replaceChildren(...fb.items.map((x) => {
    const tr = document.createElement("tr");
    [new Date(x.created_at).toLocaleString("ru-RU"), x.kind === "flag" ? "жалоба" : "👎", x.reason || "—", x.question || "—",
     x.refused ? (x.refusal_category || "да") : "нет"].forEach((v) => {
      const td = document.createElement("td"); td.textContent = v; tr.appendChild(td);
    });
    return tr;
  }));
  const r = await api("/admin/users", { admin: true });
  $("users").innerHTML = r.items.map((u) =>
    `<tr><td>${esc(u.email)}</td><td>${esc(u.shops_count)}</td><td>${u.blocked ? "заблокирован" : "активен"}</td>` +
    `<td>${u.support_access_until ? esc(u.support_access_until.slice(0, 16).replace("T", " ")) : "—"}</td>` +
    `<td class="row"><button class="secondary" data-block="${esc(u.id)}" data-on="${u.blocked ? 0 : 1}">${u.blocked ? "Разблокировать" : "Заблокировать"}</button>` +
    `<button class="secondary" data-shops="${esc(u.id)}">Магазины</button></td></tr>`).join("");
  show("users-section", true);
}

async function showUserShops(id) {
  try {
    const r = await api(`/admin/users/${id}/shops`, { admin: true });
    $("user-shops").innerHTML = "<h2>Магазины (доступ поддержки до " + esc(r.access_until.slice(0, 16).replace("T", " ")) + ")</h2>" +
      "<ul>" + r.items.map((s) => `<li>${esc(s.name)} · ${esc(s.timezone)} · ${esc(s.language)}</li>`).join("") + "</ul>";
  } catch (e) {
    $("user-shops").innerHTML = `<p class="error">${esc(e.message)}</p>`;
  }
}

async function loadErrors() {
  const r = await api("/admin/errors", { admin: true });
  $("errors").innerHTML = r.items.map((e) =>
    `<tr><td>${esc(e.where)}<div class="muted">${esc(e.kind)}${e.platform ? " · " + esc(e.platform) : ""}</div></td>` +
    `<td>${esc(e.exc_type)}</td><td>${esc(e.message)}</td><td>${esc(e.count)}</td>` +
    `<td>${esc(e.last_seen.slice(0, 16).replace("T", " "))}</td></tr>`).join("");
  show("errors-section", true);
}

// ---------- продавец по номеру (К-21, К-33 А3) ----------
let sellerNumber = "";
function sellerCard(v) {
  const sub = v.subscription ? (v.subscription.state || "—") : "—";
  const specials = (v.special_access || []).filter((s) => !s.cancelled_at)
    .map((s) => esc(s.from.slice(0, 10)) + " — " + esc(s.until.slice(0, 10)) + (s.comment ? " · " + esc(s.comment) : "")).join("<br>") || "нет";
  const pres = v.presentation_mode;
  return "<table><tbody>" +
    `<tr><th>Номер</th><td>${esc(v.number)}</td></tr>` +
    `<tr><th>Аккаунт</th><td>${esc(v.account)} · ${esc(v.email || "—")}</td></tr>` +
    `<tr><th>Магазин</th><td>${esc(v.shop_name || "—")} · Kaspi: ${esc(v.kaspi_status || "не подключён")}${v.seller_id ? " · ID " + esc(v.seller_id) : ""}</td></tr>` +
    `<tr><th>Подписка</th><td>${esc(sub)}</td></tr>` +
    `<tr><th>Доступ без подписки</th><td>${specials}</td></tr>` +
    `<tr><th>Режим презентации</th><td>${pres ? "включён — пример остатков и себестоимости; прайс в Kaspi не отдаётся" : "выключен"}</td></tr>` +
    "</tbody></table>" +
    '<div class="row" style="margin-top:8px">' +
    `<button class="secondary" data-sa="special" data-months="1">Без подписки 1 мес.</button>` +
    `<button class="secondary" data-sa="special" data-months="3">3 мес.</button>` +
    `<button class="secondary" data-sa="special" data-months="6">6 мес.</button>` +
    `<button class="secondary" data-sa="special-cancel">Отменить доступ без подписки</button>` +
    `<button class="secondary" data-sa="presentation" data-on="${pres ? 0 : 1}">${pres ? "Выключить режим презентации" : "Включить режим презентации"}</button>` +
    `<button class="secondary" data-sa="reconnect">Окно нового токена 24 ч</button>` +
    `<button class="secondary" data-sa="block" data-on="${v.account === "blocked" ? 0 : 1}">${v.account === "blocked" ? "Разблокировать" : "Заблокировать"}</button>` +
    "</div>";
}

async function findSeller() {
  $("seller-error").textContent = "";
  sellerNumber = $("seller-number").value.trim();
  if (!sellerNumber) return;
  try { $("seller-card").innerHTML = sellerCard(await api(`/admin/sellers/${encodeURIComponent(sellerNumber)}`, { admin: true })); }
  catch (e) { $("seller-card").innerHTML = ""; $("seller-error").textContent = e.message; }
}

async function sellerAction(t) {
  const n = encodeURIComponent(sellerNumber);
  const a = t.dataset.sa;
  const plan = {
    "special": [`Выдать доступ без подписки на ${t.dataset.months} мес.?`, `/admin/sellers/${n}/special-access`,
      () => ({ months: Number(t.dataset.months), comment: prompt("Комментарий (необязательно)", "") || "" })],
    "special-cancel": ["Отменить доступ без подписки?", `/admin/sellers/${n}/special-access/cancel`, () => ({})],
    "presentation": [t.dataset.on === "1"
      ? "Включить режим презентации? Товарам без своих цифр будет показан пример остатков и себестоимости (пометка «пример»). Прайс-лист в Kaspi отдаваться не будет."
      : "Выключить режим презентации? Все примеры будут удалены, цифры продавца останутся.",
      `/admin/sellers/${n}/presentation`, () => ({ enabled: t.dataset.on === "1" })],
    "reconnect": ["Открыть окно нового токена на 24 часа?", `/admin/sellers/${n}/reconnect`, () => ({})],
    "block": [t.dataset.on === "1" ? "Заблокировать продавца?" : "Разблокировать продавца?", `/admin/sellers/${n}/block`,
      () => ({ blocked: t.dataset.on === "1" })],
  }[a];
  if (!plan || !confirm(plan[0])) return;
  try {
    const v = await api(plan[1], { method: "POST", body: { ...plan[2](), confirm: true }, admin: true });
    $("seller-card").innerHTML = sellerCard(v);
  } catch (e) { $("seller-error").textContent = e.message; }
}

async function loadAll() {
  $("panel-error").textContent = "";
  show("seller-section", true);
  try { await loadStats(); await loadFlags(); await loadUsers(); await loadErrors(); }
  catch (e) { $("panel-error").textContent = e.message; }
}

$("send-code").onclick = sendCode;
$("verify-code").onclick = verifyCode;
$("tf-setup").onclick = setupTwoFactor;
$("tf-enable").onclick = enableTwoFactor;
$("reload").onclick = loadAll;
$("seller-find").onclick = findSeller;
$("logout").onclick = () => { sessionStorage.removeItem("satti-admin-token"); location.reload(); };

document.addEventListener("click", async (ev) => {
  const t = ev.target;
  if (t.dataset.flag) {
    try { await api(`/admin/flags/${t.dataset.flag}`, { method: "PUT", body: { enabled: t.dataset.on === "1" }, admin: true }); loadFlags(); }
    catch (e) { $("panel-error").textContent = e.message; }
  }
  if (t.dataset.block) {
    try { await api(`/admin/users/${t.dataset.block}/block`, { method: "POST", body: { blocked: t.dataset.on === "1" }, admin: true }); loadUsers(); }
    catch (e) { $("panel-error").textContent = e.message; }
  }
  if (t.dataset.shops) showUserShops(t.dataset.shops);
  if (t.dataset.sa) sellerAction(t);
});

if (token) afterSignIn(); else { show("sign-in", true); }
