// Read-only startup smoke. No login, signup, quote, payment or provider mutation.
import assert from 'node:assert/strict';
import { existsSync, mkdirSync, readFileSync, realpathSync, writeFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = realpathSync.native(resolve(dirname(fileURLToPath(import.meta.url)), '../..'));
const require = createRequire(resolve(root, 'frontend/package.json'));
const { chromium } = require('playwright-core');
const c = JSON.parse(readFileSync(resolve(root, '.dev/config.json'), 'utf8'));
assert.equal(c.root, root, 'Runtime config must belong to this checkout');
const candidates = [
  process.env.CHROMIUM_PATH,
  'C:/Program Files/Google/Chrome/Application/chrome.exe',
  '/usr/bin/chromium', '/usr/bin/chromium-browser', '/usr/bin/google-chrome',
  '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
].filter(Boolean);
const executablePath = candidates.find(existsSync);
assert.ok(executablePath, 'Install Chromium/Chrome or set CHROMIUM_PATH; browser smoke is not passed without a browser.');
const base = 'http://127.0.0.1:' + c.ports.frontend;
const api = 'http://127.0.0.1:' + c.ports.api;
const out = resolve(root, '.dev/evidence');
mkdirSync(out, { recursive: true });
const browser = await chromium.launch({ executablePath, headless: true });
const results = [];
try {
  for (const locale of ['en', 'ar']) {
    const context = await browser.newContext({ viewport: { width: locale === 'ar' ? 390 : 1360, height: 900 } });
    await context.addInitScript((value) => localStorage.setItem('ceopro_locale', value), locale);
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', (error) => errors.push(error.message));
    for (const path of ['/login', '/signup']) {
      await page.goto(base + path, { waitUntil: 'networkidle' });
      await page.locator('input[type="email"]').waitFor();
      assert.equal(await page.locator('html').getAttribute('dir'), locale === 'ar' ? 'rtl' : 'ltr');
      assert.ok((await page.locator('body').innerText()).length > 80);
      await page.screenshot({ path: resolve(out, locale + '-' + path.slice(1) + '.png'), fullPage: true });
      results.push({ locale, route: path, rendered: true, direction: locale === 'ar' ? 'rtl' : 'ltr' });
    }
    const ready = await context.request.get(base + '/api/health/ready');
    assert.equal(ready.status(), 200);
    assert.equal((await ready.json()).status, 'ok');
    const plans = await context.request.get(base + '/api/billing/plans');
    assert.equal(plans.status(), 200);
    const owner = await context.request.get(api + '/platform/billing/admin-views/overview');
    assert.equal(owner.status(), 401);
    await page.goto(base + '/platform/billing', { waitUntil: 'networkidle' });
    await page.waitForURL('**/login**');
    assert.deepEqual(errors, []);
    results.push({ locale, proxy: 200, plans: 200, unauthenticatedOwner: 401, protectedRoute: 'login redirect', pageErrors: 0 });
    await context.close();
  }
  writeFileSync(resolve(out, 'browser-smoke.json'), JSON.stringify({ result: 'PASS', checks: results }, null, 2));
  console.log('PASS: real Chrome English/Arabic login/signup, RTL, Python proxy/plans, owner denial; no mutations.');
} finally {
  await browser.close();
}
