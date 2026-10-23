import assert from 'node:assert/strict';
import { chromium } from 'playwright-core';
import { readFile } from 'node:fs/promises';

const base = process.env.APP_URL || 'http://127.0.0.1:5178';
const locale = process.env.E2E_LOCALE || 'en';
const email = process.env.E2E_EMAIL;
const password = process.env.E2E_PASSWORD;
const marker = process.env.E2E_PRODUCT_MARKER;
if (!email || !password || !marker) throw new Error('Disposable pricing fixture credentials and marker are required.');
const messages = JSON.parse(await readFile(new URL(`../../src/assets/locales/${locale}.json`, import.meta.url), 'utf8'));
const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH });
try {
  const page = await browser.newPage({ viewport: { width: locale === 'ar' ? 390 : 1365, height: 900 } });
  await page.addInitScript((language) => localStorage.setItem('ceopro_locale', language), locale);
  await page.goto(`${base}/login`);
  await page.locator('input[type="email"]').fill(email);
  await page.locator('input[type="password"]').fill(password);
  await page.locator('button[type="submit"]').click();
  await page.waitForURL((url) => !url.pathname.startsWith('/login'), { timeout: 30000 });
  const row = page.locator('tr').filter({ hasText: marker }).first();
  await page.goto(`${base}/pricing`);
  await row.waitFor();
  const originalPrice = await row.locator('td').nth(1).innerText();
  const recommendation = page.waitForResponse((response) => response.request().method() === 'POST' &&
    response.url().includes('/pricing/recommend?product_id='));
  await row.getByRole('button', { name: messages.pricing.list.getRecommendation }).click();
  const response = await recommendation;
  assert.equal(response.status(), 200);
  const result = await response.json();
  assert.ok(['OK', 'UNKNOWN'].includes(result.status), `Unexpected recommendation status: ${result.status}`);
  if (result.status === 'OK') {
    assert.ok(Number.isFinite(Number(result.suggested_price)));
    assert.ok(Number.isFinite(Number(result.current_price)));
    const dialog = page.getByRole('dialog');
    await dialog.getByText(messages.pricing.actions[result.action]).waitFor();
    await dialog.getByText(String(result.matched_competitor_count), { exact: true }).waitFor();
    console.log(`Pricing browser: actual recommendation, action=${result.action}, evidence=${result.matched_competitor_count}, locale=${locale}`);
  } else {
    await page.getByRole('dialog').getByText(messages.pricing.modal.unknownTitle).waitFor();
    console.log(`Pricing browser: backend truthfully reported insufficient evidence, locale=${locale}`);
  }
  assert.equal(await page.locator('html').getAttribute('dir'), locale === 'ar' ? 'rtl' : 'ltr');
  assert.equal(await page.locator('button').filter({ hasText: /Apply|تطبيق/ }).count(), 0, 'recommendation is advisory; no price is auto-applied');
  assert.equal((await row.locator('td').nth(1).innerText()), originalPrice, 'recommendation did not change product price');
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth) > 1, false, 'no horizontal overflow');
  console.log(`PASS pricing browser workflow (${locale}, ${locale === 'ar' ? 'mobile RTL' : 'desktop'}): authenticated request, validated output, unchanged product price.`);
} finally {
  await browser.close();
}
