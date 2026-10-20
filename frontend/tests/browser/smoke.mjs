// Signs in and opens every main screen in one language, width and theme,
// failing on page errors, failed API calls, untranslated keys on screen or
// sideways scrolling. Needs the app running (backend + `npm run dev`).
//
//   APP_URL=http://localhost:5173 API_URL=http://localhost:8000 \
//   E2E_EMAIL=... E2E_PASSWORD=... [E2E_LOCALE=ar] [E2E_WIDTH=390] [E2E_THEME=dark] \
//   [CHROMIUM_PATH=/path/to/chrome] node tests/browser/smoke.mjs
import { chromium } from 'playwright-core';

const BASE = process.env.APP_URL || 'http://localhost:5173';
const API = process.env.API_URL || 'http://localhost:8000';
const { E2E_EMAIL: email, E2E_PASSWORD: password } = process.env;
const locale = process.env.E2E_LOCALE || 'en';
const width = Number(process.env.E2E_WIDTH || 1440);
const theme = process.env.E2E_THEME || '';
if (!email || !password) {
  console.error('Set E2E_EMAIL and E2E_PASSWORD to an account that has finished setup.');
  process.exit(2);
}

const browser = await chromium.launch(process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {});
const context = await browser.newContext({ viewport: { width, height: 900 } });
await context.addInitScript(([l, th]) => { localStorage.setItem('ceopro_locale', l); if (th) localStorage.setItem('apex_theme', th); }, [locale, theme]);
const page = await context.newPage();
let problems = [];
page.on('pageerror', (e) => problems.push(`page error: ${String(e).slice(0, 200)}`));
page.on('response', (r) => { if (r.status() >= 400 && r.url().startsWith(API)) problems.push(`${r.status()} ${r.request().method()} ${r.url().slice(API.length)}`); });

await page.goto(`${BASE}/login`);
await page.fill('input[type="email"]', email);
await page.fill('input[type="password"]', password);
await page.click('button[type="submit"]');
await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 30000 });
const token = await page.evaluate(() => JSON.parse(localStorage.getItem('ceopro_auth_session') || '{}').accessToken);
const get = async (path) => (await page.request.get(API + path, { headers: { Authorization: `Bearer ${token}` } })).json().catch(() => null);
const product = (await get('/products?limit=1'))?.products?.[0];
const competitor = (await get('/discovery/competitors?limit=1'))?.competitors?.[0];

const routes = ['/dashboard', '/products', '/products/new', product && `/products/${product.product_id}`, product && `/products/${product.product_id}/edit`,
  '/demand', '/pricing', '/pricing/report', '/reports', '/market', competitor && `/market/competitors/${competitor.competitor_id}`, '/market/competitors/new',
  '/market/search-scope', '/market/sources', '/market/leaderboard', '/market/trends', '/marketing', '/ai-advisor', '/connect-data', '/billing',
  '/workspaces/new', ...['profile', 'company', 'team', 'notifications', 'preferences', 'security'].map((tab) => `/settings?tab=${tab}`)].filter(Boolean);
// Text that looks like a translation key ("section.item.label"), not a domain or file name.
const KEY = '^[a-z][a-zA-Z]+(\\.[a-zA-Z0-9_-]+)+$';
let failures = 0;
for (const route of routes) {
  problems = [];
  await page.goto(BASE + route, { waitUntil: 'domcontentloaded' });
  await page.waitForLoadState('networkidle', { timeout: 20000 }).catch(() => {});
  await page.waitForTimeout(800);
  const found = await page.evaluate((re) => {
    const rx = new RegExp(re);
    const looksLikeKey = (t) => rx.test(t) && !/\.(com|net|org|io|jo|sa|ae|csv|xlsx|pdf|example)$/i.test(t);
    const raw = [];
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    while (walker.nextNode()) { const t = walker.currentNode.textContent.trim(); if (looksLikeKey(t)) raw.push(t); }
    for (const el of document.querySelectorAll('[placeholder],[aria-label],[title]')) {
      for (const a of ['placeholder', 'aria-label', 'title']) { const v = el.getAttribute(a); if (v && looksLikeKey(v)) raw.push(`${a}=${v}`); }
    }
    return { raw: [...new Set(raw)], overflow: document.documentElement.scrollWidth - innerWidth };
  }, KEY);
  const issues = [...problems, ...found.raw.map((r) => `untranslated: ${r}`), ...(found.overflow > 1 ? [`scrolls sideways by ${found.overflow}px`] : [])];
  failures += issues.length ? 1 : 0;
  console.log(`${issues.length ? '✗' : '✓'} ${route}${issues.map((i) => `\n    ${i}`).join('')}`);
}
await browser.close();
console.log(`\n${routes.length - failures}/${routes.length} screens clean (${locale}, ${width}px${theme ? `, ${theme}` : ''})`);
process.exit(failures ? 1 : 0);
