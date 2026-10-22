import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { chromium } from 'playwright-core';

const appUrl = process.env.APP_URL || 'http://127.0.0.1:15171';
const email = process.env.FORECAST_BROWSER_EMAIL;
const password = process.env.FORECAST_BROWSER_PASSWORD;
const productName = process.env.FORECAST_BROWSER_PRODUCT;
const productId = process.env.FORECAST_BROWSER_PRODUCT_ID;
const chromePath = process.env.CHROMIUM_PATH;
assert.ok(email && password && productName && productId, 'forecast browser fixture credentials and product are required');

const browser = await chromium.launch(chromePath ? { executablePath: chromePath } : {});
try {
  for (const locale of ['en', 'ar']) {
    const copy = JSON.parse(readFileSync(new URL(`../../src/assets/locales/${locale}.json`, import.meta.url), 'utf8')).demandApex;
    const context = await browser.newContext({ viewport: { width: locale === 'ar' ? 390 : 1440, height: 900 } });
    await context.addInitScript((language) => localStorage.setItem('ceopro_locale', language), locale);
    const page = await context.newPage();
    const errors = [];
    page.on('response', (response) => {
      const expectedPlatformDenial = response.status() === 403 && response.url().endsWith('/platform/me');
      if (response.status() >= 400 && !expectedPlatformDenial) errors.push(`${response.status()} ${response.request().method()} ${response.url()}`);
    });
    page.on('pageerror', (error) => errors.push(String(error)));
    await page.goto(`${appUrl}/login`);
    await page.fill('input[type="email"]', email);
    await page.fill('input[type="password"]', password);
    await page.click('button[type="submit"]');
    await page.waitForURL((url) => !url.pathname.startsWith('/login'), { timeout: 20000 });
    await page.goto(`${appUrl}/demand`);
    const select = page.locator('select[aria-label]').first();
    try {
      await select.waitFor({ state: 'visible', timeout: 20000 });
    } catch {
      throw new Error(`Demand page has no product selector (${locale}); URL=${page.url()} body=${(await page.locator('body').innerText()).slice(0, 600)}; errors=${errors.join('; ')}`);
    }
    await select.selectOption(productId);
    const generate = page.getByRole('button', { name: copy.actions.generateSelected }).first();
    const responsePromise = page.waitForResponse((response) =>
      response.url().includes(`/dashboard/products/${productId}/forecast`) && response.request().method() === 'POST');
    await generate.click();
    const response = await responsePromise;
    assert.equal(response.status(), 200, `forecast API returned ${response.status()}`);
    const result = await response.json();
    assert.equal(result.status, 'OK');
    assert.ok(Number.isFinite(result.expected_demand));
    await page.getByRole('heading', { name: copy.history.title }).waitFor({ timeout: 15000 });
    await page.locator('.apex-table-wrap table tbody tr').first().waitFor({ timeout: 15000 });
    if (locale === 'ar') assert.equal(await page.locator('.apex-page').getAttribute('dir'), 'rtl');
    assert.deepEqual(errors, [], `browser errors in ${locale}`);
    console.log(`PASS demand selection/generation/history (${locale}, ${locale === 'ar' ? '390px RTL' : 'desktop'}, source=${result.source})`);
    await context.close();
  }
} finally {
  await browser.close();
}
