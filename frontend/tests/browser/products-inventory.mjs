import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { chromium } from 'playwright-core';

const state = process.env.KEEL_VERIFICATION_STATE;
assert.ok(state, 'KEEL_VERIFICATION_STATE is required');
const owner = JSON.parse(await readFile(`${state}/competitor-browser-fixture.json`, 'utf8'));
const staff = JSON.parse(await readFile(`${state}/products-browser-fixture.json`, 'utf8'));
const importFixture = JSON.parse(await readFile(`${state}/import-browser-fixture.json`, 'utf8'));
const api = process.env.API_URL || 'http://127.0.0.1:8000';
const app = process.env.APP_URL || 'http://127.0.0.1:5178';
const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH });

async function login(context, email, password, locale) {
  await context.addInitScript((value) => localStorage.setItem('ceopro_locale', value), locale);
  const page = await context.newPage();
  await page.goto(`${app}/login`);
  await page.locator('input[type="email"]').fill(email);
  await page.locator('input[type="password"]').fill(password);
  await page.locator('button[type="submit"]').click();
  await page.waitForURL((url) => !url.pathname.startsWith('/login'), { timeout: 20000 });
  const token = await page.evaluate(() => JSON.parse(localStorage.getItem('ceopro_auth_session') || '{}').accessToken);
  assert.ok(token, 'login must establish a backend-issued session');
  return { page, token, headers: { Authorization: `Bearer ${token}` } };
}

try {
  const ownerContext = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const ownerSession = await login(ownerContext, owner.email, owner.password, 'en');
  const { page } = ownerSession;
  const marker = `PHASE6 Product ${Date.now()}`;
  await page.goto(`${app}/products/new`);
  await page.getByLabel('Product name').fill(marker);
  await page.getByLabel('Current price').fill('12.50');
  await page.getByLabel('Currency').fill('JOD');
  const createResponse = page.waitForResponse((r) => r.url().endsWith('/products') && r.request().method() === 'POST');
  await page.getByRole('button', { name: 'Create product' }).click();
  const created = await (await createResponse).json();
  assert.ok(created.product_id, 'owner creates product through React and FastAPI');
  await page.waitForURL((url) => url.pathname === '/products');

  await page.goto(`${app}/products/${created.product_id}/edit`);
  await page.getByLabel('Product name').fill(`${marker} Edited`);
  const editResponse = page.waitForResponse((r) => r.url().endsWith(`/products/${created.product_id}`) && r.request().method() === 'PATCH');
  await page.locator('.products-form').first().getByRole('button', { name: 'Save changes' }).click();
  assert.equal((await (await editResponse).json()).product_name.en, `${marker} Edited`);
  await page.waitForURL((url) => url.pathname === '/products');

  await page.goto(`${app}/products/${created.product_id}/edit`);
  await page.getByLabel('Quantity').fill('10.1234');
  const stockResponse = page.waitForResponse((r) => r.url().endsWith(`/products/${created.product_id}/inventory`) && r.request().method() === 'PATCH');
  await page.locator('.products-form-card').nth(1).getByRole('button', { name: 'Save' }).click();
  const stock = await (await stockResponse).json();
  assert.equal(Number(stock.stock_quantity), 10.1234, 'manual stock saves four decimal places');
  await page.reload();
  assert.equal(await page.getByLabel('Quantity').inputValue(), '10.1234', 'stock persists after reload');

  const ownerRead = await page.request.get(`${api}/products/${created.product_id}`, { headers: ownerSession.headers });
  assert.equal(ownerRead.status(), 200);
  const finalProduct = await ownerRead.json();
  assert.equal(finalProduct.product_name.en, `${marker} Edited`);
  assert.equal(Number(finalProduct.inventory.stock_quantity), 10.1234);
  console.log('PASS owner browser journey: created, edited, four-decimal stock persisted in real API data (English desktop).');
  await ownerContext.close();

  const staffContext = await browser.newContext({ viewport: { width: 390, height: 844 } });
  const staffSession = await login(staffContext, staff.email, staff.password, 'ar');
  const staffPage = staffSession.page;
  await staffPage.goto(`${app}/products`);
  await staffPage.getByRole('heading', { level: 1 }).waitFor();
  assert.equal(await staffPage.locator('button').filter({ hasText: 'إضافة منتج' }).count(), 0,
    'staff UI must not expose product creation');
  const guessedId = created.product_id;
  const denied = [];
  denied.push(await staffPage.request.post(`${api}/products`, { headers: staffSession.headers,
    data: { product_name: { en: `${marker} Unauthorized` }, current_price: 1, currency: 'JOD' } }));
  denied.push(await staffPage.request.patch(`${api}/products/${guessedId}`, { headers: staffSession.headers,
    data: { product_name: { en: 'Unauthorized edit' } } }));
  denied.push(await staffPage.request.delete(`${api}/products/${guessedId}`, { headers: staffSession.headers }));
  denied.push(await staffPage.request.patch(`${api}/products/${guessedId}/inventory`, { headers: staffSession.headers,
    data: { stock_quantity: 99 } }));
  assert.deepEqual(denied.map((r) => r.status()), [403, 403, 403, 403], 'direct API writes must be denied server-side');
  const stillOwned = await staffPage.request.get(`${api}/products/${guessedId}`, { headers: ownerSession.headers });
  assert.equal(stillOwned.status(), 200);
  assert.equal(Number((await stillOwned.json()).inventory.stock_quantity), 10.1234, 'denied writes do not change stock');
  assert.equal(await staffPage.evaluate(() => document.documentElement.scrollWidth - innerWidth), 0, 'Arabic mobile must not overflow');
  assert.equal(await staffPage.locator('html').getAttribute('dir'), 'rtl');
  console.log('PASS staff security journey: Arabic mobile UI restriction, four direct API mutations denied, no cross-role state change.');
  await staffContext.close();

  const otherContext = await browser.newContext();
  const otherPage = await otherContext.newPage();
  const otherToken = importFixture.other_token;
  const crossTenant = await otherPage.request.get(`${api}/products/${guessedId}`, {
    headers: { Authorization: `Bearer ${otherToken}` },
  });
  assert.equal(crossTenant.status(), 404, 'cross-tenant guessed product id remains hidden');
  const crossTenantWrite = await otherPage.request.patch(`${api}/products/${guessedId}/inventory`, {
    headers: { Authorization: `Bearer ${otherToken}` }, data: { stock_quantity: 500 },
  });
  assert.equal(crossTenantWrite.status(), 404, 'cross-tenant stock write is hidden');
  const ownerDelete = await otherPage.request.delete(`${api}/products/${guessedId}`, { headers: ownerSession.headers });
  assert.equal(ownerDelete.status(), 200, 'owner deletion is authorized and soft-deletes the catalog row');
  assert.equal((await otherPage.request.get(`${api}/products/${guessedId}`, { headers: ownerSession.headers })).status(), 404);
  console.log('PASS cross-tenant browser API check: guessed read/write are hidden; owner delete remains authorized (soft delete).');
  await otherContext.close();
} finally {
  await browser.close();
}
