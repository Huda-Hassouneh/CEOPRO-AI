import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { chromium } from 'playwright-core';

const fixturePath = process.env.KEEL_VERIFY_FIXTURE;
const fixture = JSON.parse(readFileSync(fixturePath, 'utf8'));
const app = process.env.APP_URL || 'http://127.0.0.1:5178';
const api = process.env.API_URL || 'http://127.0.0.1:8000';
const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH, headless: true });
const page = await browser.newPage({ viewport: { width: 1365, height: 900 } });
let count = 0;
const pass = (name) => { count += 1; console.log('PASS ' + name); };
try {
  await page.goto(app + '/login');
  await page.locator('input[type="email"]').fill(fixture.email);
  await page.locator('input[type="password"]').fill(fixture.password);
  await page.locator('button[type="submit"]').click();
  await page.waitForURL((url) => !url.pathname.startsWith('/login'), { timeout: 30000 });
  const token = await page.evaluate(() => JSON.parse(localStorage.getItem('ceopro_auth_session') || '{}').accessToken);
  assert.ok(token, 'authenticated session exists');

  await page.goto(app + '/connect-data');
  await page.locator('.connect-data-page').waitFor();
  await page.getByRole('button', { name: 'Add Data Source' }).first().click();
  await page.getByRole('button', { name: /Connect Shopify/ }).click();
  const shopForm = page.locator('form.connect-store-form');
  await shopForm.waitFor();
  const shopUrl = shopForm.locator('input').first();
  const shopSubmit = shopForm.locator('button[type="submit"]');
  await shopUrl.fill('https://example.com');
  await shopForm.locator('input[type="checkbox"]').first().check();
  assert.equal(await shopSubmit.isDisabled(), true, 'non-Shopify host cannot start OAuth');
  await shopUrl.fill('phase7-synthetic.myshopify.com');
  assert.equal(await shopSubmit.isEnabled(), true, 'valid Shopify development-store address enables OAuth');
  pass('Shopify connection form and domain validation; no OAuth/provider request submitted');

  await page.goto(app + '/connect-data');
  await page.locator('.connect-data-page').waitFor();
  await page.getByRole('button', { name: 'Add Data Source' }).first().click();
  await page.getByRole('button', { name: /Connect WooCommerce/ }).click();
  const wooForm = page.locator('form.connect-store-form');
  await wooForm.waitFor();
  await wooForm.locator('input').nth(0).fill('https://store.example.test');
  await wooForm.locator('input[type="checkbox"]').first().check();
  const wooSubmit = wooForm.locator('button[type="submit"]');
  assert.equal(await wooSubmit.isDisabled(), true, 'WooCommerce credentials are required');
  await wooForm.locator('input[type="password"]').nth(0).fill('ck_' + 'a'.repeat(40));
  await wooForm.locator('input[type="password"]').nth(1).fill('cs_' + 'b'.repeat(40));
  assert.equal(await wooSubmit.isEnabled(), true, 'synthetic read-only key shapes enable local form validation');
  pass('WooCommerce URL/credential form validation; no credentials submitted to a store');

  const loginState = await page.evaluate(() => JSON.parse(localStorage.getItem('ceopro_auth_session') || '{}'));
  const optionsResponse = await page.request.get(api + '/marketing/options', {
    headers: { Authorization: 'Bearer ' + loginState.accessToken },
  });
  assert.equal(optionsResponse.status(), 200, 'authenticated marketing options use the real API');
  const options = await optionsResponse.json();
  assert.ok(options.capabilities && Object.hasOwn(options.capabilities, 'image_generation'));
  await page.setViewportSize({ width: 390, height: 844 });
  await page.evaluate(() => localStorage.setItem('ceopro_locale', 'ar'));
  await page.goto(app + '/marketing');
  await page.locator('main').waitFor();
  assert.equal(await page.locator('html').getAttribute('dir'), 'rtl');
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
  pass('Marketing Studio authenticated route, real capability response, Arabic RTL mobile state');
  console.log('Phase 7 browser smoke: ' + count + ' passed; provider connection and image-generation journeys not invoked');
} finally {
  await browser.close();
}

