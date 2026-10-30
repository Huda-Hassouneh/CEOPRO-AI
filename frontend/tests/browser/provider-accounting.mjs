// Real owner UI/API and disposable PostgreSQL; never a paid provider request.
import { chromium } from 'playwright-core';
import { readFileSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
const { APP_URL: base, E2E_PASSWORD: password, E2E_OUTPUT: output } = process.env;
if (process.env.KEEL_OWNER_BROWSER_ISOLATED !== 'YES' || !/^http:\/\/127\.0\.0\.1:\d+$/.test(base || '')) throw new Error('Disposable owner runtime required');
const fixture = JSON.parse(readFileSync(process.env.E2E_FIXTURE_FILE, 'utf8'));
const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH, headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
page.setDefaultTimeout(20000);
const errors = [];
page.on('pageerror', error => errors.push(error.message));
try {
  await page.goto(base + '/login');
  await page.locator('input[type=email]').fill(fixture.owner.email);
  await page.locator('input[type=password]').fill(password);
  let login = page.waitForResponse(r => new URL(r.url()).pathname === '/api/auth/login');
  await page.locator('button[type=submit]').click();
  if ((await login).status() === 409) {
    login = page.waitForResponse(r => new URL(r.url()).pathname === '/api/auth/login');
    await page.getByRole('button', { name: /KEEL Platform/ }).click();
    if ((await login).status() !== 200) throw new Error('Owner workspace login failed');
  }
  await page.waitForURL(url => url.pathname !== '/login');
  await page.goto(base + '/admin/billing');
  await page.getByRole('link', { name: 'Provider Accounting', exact: true }).click();
  if (!page.url().endsWith('?tab=provider-accounting')) throw new Error('Sibling tab URL incorrect');
  await page.getByRole('cell', { name: 'brave_search', exact: true }).waitFor();
  await page.getByRole('cell', { name: 'Missing price', exact: true }).first().waitFor();
  // Direct navigation reload and loading state, with the real GET delayed only.
  await page.route('**/api/platform/billing/provider-accounting', async route => {
    if (route.request().method() === 'GET') await new Promise(resolve => setTimeout(resolve, 500));
    await route.continue();
  });
  await page.reload();
  await page.getByRole('status', { name: /loading/i }).waitFor();
  await page.getByRole('cell', { name: 'brave_search', exact: true }).waitFor();
  await page.unroute('**/api/platform/billing/provider-accounting');
  await page.getByRole('button', { name: 'Add accounting schedule' }).click();
  const dialog = page.getByRole('dialog');
  await dialog.getByRole('button', { name: 'Save', exact: true }).click();
  await dialog.getByText(/Enter a valid value/).first().waitFor();
  const provider = 'synthetic_browser_accounting';
  for (const [label, value] of Object.entries({ Provider: provider, Operation: 'search', 'USD cost/unit': '0.03', 'Safety margin': '0', 'Source / provenance': 'SYNTHETIC BROWSER invoice', 'Verified date': '2026-10-30', 'Reason / justification': 'SYNTHETIC browser persistence proof' })) await dialog.getByLabel(label, { exact: true }).fill(value);
  await page.screenshot({ path: resolve(output, 'provider-accounting-form.png'), fullPage: true });
  // A safe simulated API error must keep the form, then a real retry succeeds.
  await page.route('**/api/platform/billing/provider-accounting', route => route.request().method() === 'PUT' ? route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ detail: 'sensitive internal fixture must not render' }) }) : route.continue());
  await dialog.getByRole('button', { name: 'Save', exact: true }).click();
  await dialog.getByRole('button', { name: 'Confirm', exact: true }).click();
  await dialog.getByRole('alert').waitFor();
  if ((await dialog.innerText()).includes('sensitive internal')) throw new Error('Raw backend error leaked');
  await page.unroute('**/api/platform/billing/provider-accounting');
  const saved = page.waitForResponse(r => new URL(r.url()).pathname === '/api/platform/billing/provider-accounting' && r.request().method() === 'PUT');
  await dialog.getByRole('button', { name: 'Save', exact: true }).click();
  await dialog.getByRole('button', { name: 'Confirm', exact: true }).click();
  const response = await saved;
  if (response.status() !== 200) throw new Error('Save failed: ' + response.status());
  const authoritative = (await response.json()).schedules.find(row => row.provider === provider);
  if (authoritative.unit_cost_usd !== '0.030000000000') throw new Error('Authoritative decimal differs');
  await page.getByText('Provider accounting schedule saved.', { exact: true }).waitFor();
  await page.reload();
  let row = page.getByRole('row').filter({ has: page.getByRole('cell', { name: provider, exact: true }) });
  await row.getByRole('cell', { name: '0.030000000000', exact: true }).waitFor();
  // Update the actual persisted schedule through the same confirmation flow.
  await row.getByRole('button', { name: 'Edit', exact: true }).click();
  await dialog.getByLabel('USD cost/unit', { exact: true }).fill('0.04');
  await dialog.getByLabel('Reason / justification', { exact: true }).fill('SYNTHETIC browser update proof');
  await dialog.getByRole('button', { name: 'Save', exact: true }).click();
  const updated = page.waitForResponse(r => r.request().method() === 'PUT' && r.url().endsWith('/provider-accounting'));
  await dialog.getByRole('button', { name: 'Confirm', exact: true }).click();
  if ((await updated).status() !== 200) throw new Error('Update failed');
  await dialog.waitFor({ state: 'hidden' });
  await page.reload();
  await page.getByRole('row').filter({ hasText: provider }).getByRole('cell', { name: '0.040000000000', exact: true }).waitFor();
  await page.screenshot({ path: resolve(output, 'provider-accounting-en.png'), fullPage: true });
  // Existing billing siblings remain navigable.
  for (const tab of ['plans', 'custom-plans', 'custom-quotes', 'promos', 'features', 'plan-features', 'subscriptions']) {
    await page.goto(base + '/admin/billing?tab=' + tab);
    await page.locator('[aria-current=page]').filter({ hasText: /./ }).last().waitFor();
  }
  await page.evaluate(() => localStorage.setItem('ceopro_locale', 'ar'));
  await page.setViewportSize({ width: 390, height: 900 });
  await page.goto(base + '/admin/billing?tab=provider-accounting');
  await page.getByRole('cell', { name: provider, exact: true }).waitFor();
  if (!await page.locator('[dir=rtl]').count()) throw new Error('Arabic RTL missing');
  if (await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 2)) throw new Error('Mobile page overflow');
  await page.screenshot({ path: resolve(output, 'provider-accounting-ar.png'), fullPage: true });
  if (errors.length) throw new Error(errors.join('; '));
  writeFileSync(resolve(output, 'provider-accounting-result.json'), JSON.stringify({ provider, unit_cost_usd: '0.04', checks: ['login', 'sibling/direct tab', 'loading', 'missing price', 'validation', 'safe error', 'create/update confirmation', 'persisted reload', 'existing tabs', 'Arabic mobile RTL'] }, null, 2));
  console.log('PASS: Provider Accounting owner browser create/update/reload and UI states; no paid provider.');
} finally { await browser.close(); }
