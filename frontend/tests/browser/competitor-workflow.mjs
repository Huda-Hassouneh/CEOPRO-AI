import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { chromium } from 'playwright-core';

const fixturePath = process.env.KEEL_VERIFY_FIXTURE;
if (!fixturePath) throw new Error('Set KEEL_VERIFY_FIXTURE to the out-of-repository synthetic fixture JSON.');
const fixture = JSON.parse(await readFile(fixturePath, 'utf8'));
const api = process.env.API_URL || 'http://127.0.0.1:8000';
const base = process.env.APP_URL || 'http://127.0.0.1:5173';
const locale = process.env.E2E_LOCALE || 'en';
const width = locale === 'ar' ? 390 : 1365;
const browser = await chromium.launch(process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {});

try {
  const page = await browser.newPage({ viewport: { width, height: 900 } });
  const failedApi = [];
  page.on('response', (response) => {
    if (response.url().startsWith(api) && response.status() >= 400) failedApi.push(`${response.status()} ${response.url()}`);
  });
  await page.addInitScript((language) => localStorage.setItem('ceopro_locale', language), locale);
  await page.goto(`${base}/login`);
  await page.locator('input[type="email"]').fill(fixture.email);
  await page.locator('input[type="password"]').fill(fixture.password);
  await page.locator('button[type="submit"]').click();
  await page.waitForURL((url) => !url.pathname.startsWith('/login'), { timeout: 30000 });
  const token = await page.evaluate(() => JSON.parse(localStorage.getItem('ceopro_auth_session') || '{}').accessToken);
  assert.ok(token, 'authenticated Python login must install the backend-issued session');
  const headers = { Authorization: `Bearer ${token}` };
  const get = async (path) => {
    const response = await page.request.get(`${api}${path}`, { headers });
    assert.equal(response.status(), 200, `${path} should be authorized for the seeded tenant`);
    return response.json();
  };

  const list = await get('/competitors?sort=name');
  const listed = list.competitors.find((item) => item.id === fixture.competitor_id || item.competitor_id === fixture.competitor_id);
  assert.ok(listed, 'manual competitor must be present in the authorized competitor directory');
  assert.match(listed.name, new RegExp(fixture.marker));
  const history = await get(`/competitors/${fixture.competitor_id}/prices`);
  assert.ok(history.prices.length >= 1, 'real price-observation history must be persisted');
  assert.equal(Number(history.prices[0].scraped_price ?? history.prices[0].price), 8.75);
  const profile = await get(`/competitors/${fixture.competitor_id}`);
  assert.match(JSON.stringify(profile), new RegExp(fixture.marker));
  const landscape = await get('/competitors/landscape');
  assert.ok(landscape.products.some((item) => item.product_id === fixture.product_id));

  await page.goto(`${base}/market`);
  await page.getByText(fixture.competitor_name, { exact: false }).first().waitFor({ timeout: 15000 });
  const pageText = await page.locator('body').innerText();
  assert.ok(pageText.includes(fixture.competitor_name), 'competitor management page renders the stored competitor');
  assert.ok(pageText.includes(fixture.marker), 'localized page includes the seeded business record');
  await page.goto(`${base}/market/competitors/${fixture.competitor_id}`);
  await page.getByText(fixture.competitor_name, { exact: false }).first().waitFor({ timeout: 15000 });
  await page.goto(`${base}/market/leaderboard`);
  await page.waitForLoadState('networkidle', { timeout: 20000 }).catch(() => {});
  assert.ok((await page.locator('body').innerText()).length > 50, 'Market Intelligence route renders a real API-backed state');
  assert.equal(await page.locator('html').getAttribute('dir'), locale === 'ar' ? 'rtl' : 'ltr');
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - innerWidth);
  assert.ok(overflow <= 1, `unexpected horizontal overflow: ${overflow}px`);
  assert.deepEqual(failedApi, [], `authenticated pages should not produce API errors: ${failedApi.join('; ')}`);
  console.log(`PASS: ${locale} ${width}px authenticated competitor workflow: directory, detail, persisted price history, product landscape, Market Intelligence, and no horizontal overflow.`);
} finally {
  await browser.close();
}
