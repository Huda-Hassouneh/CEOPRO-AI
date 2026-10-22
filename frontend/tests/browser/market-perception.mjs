import assert from 'node:assert/strict';
import { chromium } from 'playwright-core';

const api = process.env.API_URL || 'http://127.0.0.1:18001';
const base = process.env.APP_URL || 'http://127.0.0.1:15173';
const locale = process.env.E2E_LOCALE || 'en';
const messages = JSON.parse(await (await import('node:fs/promises')).readFile(new URL('../../src/assets/locales/' + locale + '.json', import.meta.url), 'utf8')).marketPerception;
const browser = await chromium.launch(process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {});
try {
  const page = await browser.newPage({ viewport: { width: locale === 'ar' ? 390 : 1365, height: 900 } });
  page.on('response', (response) => {
    if (response.url().includes('/mpi/summary')) console.log(`MPI HTTP ${response.status()}`);
  });
  await page.addInitScript((language) => localStorage.setItem('ceopro_locale', language), locale);
  await page.goto(`${base}/login`);
  await page.locator('input[type="email"]').fill(process.env.E2E_EMAIL);
  await page.locator('input[type="password"]').fill(process.env.E2E_PASSWORD);
  await page.locator('button[type="submit"]').click();
  await page.waitForURL((url) => !url.pathname.startsWith('/login'), { timeout: 30000 });
  await page.goto(`${base}/market/leaderboard`);
  await page.getByRole('heading', { name: messages.title }).waitFor();

  const scope = page.getByLabel(messages.scope);
  const action = page.getByRole('button', { name: messages.refresh });
  await action.click();
  await page.getByText(messages.reviewCount.replace('{{count}}', '1')).waitFor();
  const business = await page.request.get(`${api}/mpi/summary?subject_type=BUSINESS`, {
    headers: { Authorization: `Bearer ${await page.evaluate(() => JSON.parse(localStorage.getItem('ceopro_auth_session')).accessToken)}` },
  });
  assert.equal(business.status(), 200);
  assert.equal((await business.json()).sample_size.analyzed_count, 1);

  await scope.selectOption('PRODUCT');
  const search = page.getByRole('searchbox', { name: messages.searchProducts });
  await search.fill(process.env.E2E_PRODUCT_MARKER);
  const productSelect = page.locator('.mpi-panel .mpi-controls select').nth(1);
  const productOption = productSelect.locator('option').filter({ hasText: `${process.env.E2E_PRODUCT_MARKER} Sample Product` }).first();
  await productSelect.selectOption(await productOption.getAttribute('value'));
  await action.click();
  await page.locator('.mpi-result').waitFor();
  const lowSampleText = await page.locator('.mpi-result').innerText();
  assert.ok(lowSampleText.includes(messages.insufficient.replace('{{count}}', '1').replace('{{minimum}}', '5')),
    `expected low-sample explanation; got: ${lowSampleText}`);
  assert.equal(await page.getByText(new RegExp(`${messages.index}:`)).count(), 0, 'low-sample numeric score must be hidden');

  const emptyOption = productSelect.locator('option').filter({ hasText: `${process.env.E2E_PRODUCT_MARKER} Empty` }).first();
  await productSelect.selectOption(await emptyOption.getAttribute('value'));
  await action.click();
  await page.getByText(messages.noReviews).waitFor();

  await scope.selectOption('COMPETITOR');
  await page.locator('.mpi-panel .mpi-controls select').nth(1).selectOption({ label: process.env.E2E_COMPETITOR_NAME });
  await action.click();
  await page.getByText(new RegExp(`${messages.index}:`)).waitFor();
  assert.equal(await page.locator('html').getAttribute('dir'), locale === 'ar' ? 'rtl' : 'ltr');

  const token = await page.evaluate(() => JSON.parse(localStorage.getItem('ceopro_auth_session')).accessToken);
  const foreign = await page.request.get(`${api}/mpi/summary?subject_type=PRODUCT&subject_id=${process.env.E2E_FOREIGN_PRODUCT_ID}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  assert.equal(foreign.status(), 404, 'cross-tenant subject must be hidden');

  await page.route('**/mpi/summary?*', async (route) => route.fulfill({ status: 503, contentType: 'application/json', body: '{"detail":"unavailable"}' }), { times: 1 });
  await action.click();
  await page.getByRole('alert').getByText(messages.error).waitFor();

  const before = await page.evaluate(() => document.documentElement.scrollWidth - innerWidth);
  assert.ok(before <= 1, `horizontal overflow ${before}px`);
  console.log(`Market Perception browser journey passed (${locale}, ${locale === 'ar' ? 'mobile RTL' : 'desktop'}): business/product/competitor, search, counts, low sample, empty result, and cross-tenant 404.`);
} finally {
  await browser.close();
}
