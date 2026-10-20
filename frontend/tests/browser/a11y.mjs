// Automated accessibility audit (axe-core, WCAG 2.1 A and AA rules) of the
// public pages and every main screen, in one language, width and theme.
// Fails on any serious or critical finding. Needs the app running, like
// smoke.mjs:
//
//   APP_URL=http://localhost:5173 E2E_EMAIL=... E2E_PASSWORD=... \
//   [E2E_LOCALE=ar] [E2E_WIDTH=390] [E2E_THEME=dark] [CHROMIUM_PATH=...] node tests/browser/a11y.mjs
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { chromium } from 'playwright-core';

const require = createRequire(import.meta.url);
const AXE = readFileSync(require.resolve('axe-core/axe.min.js'), 'utf8');
const BASE = process.env.APP_URL || 'http://localhost:5173';
const { E2E_EMAIL: email, E2E_PASSWORD: password } = process.env;
const locale = process.env.E2E_LOCALE || 'en';
const width = Number(process.env.E2E_WIDTH || 1440);
const theme = process.env.E2E_THEME || '';
const FAIL_ON = new Set(['serious', 'critical']);
if (!email || !password) {
  console.error('Set E2E_EMAIL and E2E_PASSWORD to an account that has finished setup.');
  process.exit(2);
}

const browser = await chromium.launch(process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {});
const context = await browser.newContext({ viewport: { width, height: 900 }, reducedMotion: 'reduce' });
await context.addInitScript(([l, th]) => { localStorage.setItem('ceopro_locale', l); if (th) localStorage.setItem('apex_theme', th); }, [locale, theme]);
const page = await context.newPage();

async function audit(route) {
  await page.goto(BASE + route, { waitUntil: 'domcontentloaded' });
  await page.waitForLoadState('networkidle', { timeout: 20000 }).catch(() => {});
  await page.waitForTimeout(800);
  await page.addScriptTag({ content: AXE });
  const result = await page.evaluate(async () => window.axe.run(document, {
    runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'] },
    resultTypes: ['violations'],
  }));
  return result.violations;
}

const report = new Map();
const record = (route, violations) => {
  for (const v of violations) {
    const entry = report.get(v.id) || { impact: v.impact, help: v.help, routes: new Set(), nodes: 0, example: v.nodes[0]?.target?.join(' ') };
    if (process.env.A11Y_VERBOSE) v.nodes.forEach((n) => console.log(`  ${route} ${v.id}: ${n.target.join(" ")} :: ${n.html.slice(0, 120)}`));
    entry.routes.add(route);
    entry.nodes += v.nodes.length;
    report.set(v.id, entry);
  }
};

for (const route of ['/', '/login', '/signup', '/forgot-password', '/terms', '/privacy']) record(route, await audit(route));

await page.goto(`${BASE}/login`);
await page.fill('input[type="email"]', email);
await page.fill('input[type="password"]', password);
await page.click('button[type="submit"]');
await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 30000 });
const routes = ['/dashboard', '/products', '/products/new', '/demand', '/pricing', '/pricing/report', '/reports', '/market', '/market/competitors/new',
  '/market/search-scope', '/market/sources', '/market/leaderboard', '/market/trends', '/marketing', '/ai-advisor', '/connect-data',
  '/billing', '/workspaces/new', ...['profile', 'company', 'team', 'notifications', 'preferences', 'security'].map((tab) => `/settings?tab=${tab}`)];
for (const route of routes) record(route, await audit(route));

// The price comparison dialog (ladder, added-value guidance, band editor) exists only for a company that has competitor
// evidence; audit each product's dialog when there are any.
await page.goto(`${BASE}/pricing`, { waitUntil: 'domcontentloaded' });
await page.waitForLoadState('networkidle', { timeout: 20000 }).catch(() => {});
const compare = page.locator('button:has-text("Compare market"), button:has-text("قارن السوق")');
const dialogs = Math.min(await compare.count(), 6);
for (let i = 0; i < dialogs; i += 1) {
  await compare.nth(i).click();
  await page.waitForSelector('[role="dialog"] .price-ladder', { timeout: 10000 }).catch(() => {});
  await page.waitForTimeout(600);
  await page.addScriptTag({ content: AXE });
  record(`/pricing (comparison dialog ${i + 1})`, await page.evaluate(async () => (await window.axe.run(document, {
    runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'] }, resultTypes: ['violations'],
  })).violations));
  await page.keyboard.press('Escape');
  await page.waitForTimeout(300);
}
console.log(`audited ${dialogs} comparison dialog(s)`);
await browser.close();

let failing = 0;
for (const [id, v] of [...report].sort((a, b) => Number(b[1].impact === 'critical') - Number(a[1].impact === 'critical'))) {
  const fails = FAIL_ON.has(v.impact);
  failing += fails ? 1 : 0;
  console.log(`${fails ? '✗' : '·'} [${v.impact}] ${id}: ${v.help} - ${v.nodes} element(s) on ${v.routes.size} page(s), e.g. ${[...v.routes].slice(0, 3).join(', ')} :: ${v.example}`);
}
console.log(`\n${report.size} rule(s) with findings, ${failing} serious or critical (${locale}, ${width}px${theme ? `, ${theme}` : ''})`);
process.exit(failing ? 1 : 0);
