// Manual/local browser verification script for the ConnectDataPage
// "Prepare Import" flow - same convention as settings-browser.mjs /
// admin-browser.mjs (real Chromium against the real dev server + a real
// backend, not a unit test). Requires: backend on :8000, frontend
// (`npm run dev`) on :5173, a Postgres the backend can reach, and MinIO
// reachable at MINIO_ENDPOINT for the "upload succeeds" assertion.
//
// Regression #1 this guards: a stale toast previously read "Backend
// upload is not connected, so nothing was imported" for ANY failed
// upload (even once the backend was fully wired), which made a real
// server-side error look identical to the button doing nothing. Verifies
// both the success message and that a genuine failure now shows an
// accurate, visibly different (role=alert, red) error toast.
//
// Regression #2 this guards: a successful upload creates real products
// via the extraction pipeline, but prepareImport() never invalidated the
// ['products'] react-query cache (every product-mutating hook elsewhere
// in this codebase - useCreateProduct/useUpdateProduct/useDeleteProduct/
// useQuickSale - already does). Visiting Products via the app's own
// client-side navigation (no full page reload) after a successful
// upload kept showing whatever was cached before the upload - "No
// products yet" for an account with none yet - even though the new row
// was really in the database. A full reload masked this in ad hoc
// testing because a fresh page load always builds a fresh query client.
import assert from 'node:assert/strict';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { writeFileSync } from 'node:fs';
import os from 'node:os';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
// Playwright is deliberately not a project dependency (kept out of
// package.json, same as settings-browser.mjs/admin-browser.mjs) - point
// this at wherever it's installed locally to run this script.
const playwrightModulePath = process.env.PLAYWRIGHT_MODULE_PATH || 'playwright-core';
const { chromium } = await import(playwrightModulePath);
const executablePath = (process.env.CHROMIUM_PATH || process.env.PLAYWRIGHT_CHROMIUM_PATH)
  || '/opt/pw-browsers/chromium-1194/chrome-linux/chrome';
const baseUrl = process.env.CONNECT_DATA_TEST_BASE_URL || 'http://localhost:5173';
const testEmail = process.env.CONNECT_DATA_TEST_EMAIL;
const testPassword = process.env.CONNECT_DATA_TEST_PASSWORD;
const testFile = process.env.CONNECT_DATA_TEST_FILE || path.join(__dirname, '..', 'fixtures', 'connect-data-sample.xlsx');

if (!testEmail || !testPassword) {
  console.log('SKIP: set CONNECT_DATA_TEST_EMAIL/CONNECT_DATA_TEST_PASSWORD (a real signed-up user) to run this against a live stack.');
  process.exit(0);
}

const browser = await chromium.launch({ executablePath, headless: true });
const page = await browser.newPage();

await page.goto(`${baseUrl}/login`);
await page.getByRole('textbox', { name: /email/i }).fill(testEmail);
await page.getByRole('textbox', { name: /password/i }).fill(testPassword);
await page.getByRole('button', { name: 'Log In', exact: true }).click();
await page.waitForURL(/dashboard/, { timeout: 15000 });

await page.goto(`${baseUrl}/connect-data`);
await page.locator('input[type="file"]').setInputFiles(testFile);
await page.getByRole('button', { name: /prepare import/i }).click();

const toast = page.locator('.ceopro-toast');
await toast.waitFor({ timeout: 15000 });
const text = await toast.innerText();
const role = await toast.getAttribute('role');

// Whichever branch actually fires depends on whether the stack this runs
// against has a healthy MinIO right now - assert the two are never
// swapped/confused, which is exactly what the fixed bug used to do.
if (text.includes('uploaded successfully')) {
  assert.equal(role, 'status');
} else {
  assert.match(text, /upload failed/i);
  assert.equal(role, 'alert');
  assert.doesNotMatch(text, /backend upload is not connected/i);
}

console.log(`PASS: Prepare Import produced an accurate, correctly-styled toast ("${text.trim()}").`);

// Regression #2: only meaningful when the upload actually succeeded above.
if (text.includes('uploaded successfully')) {
  const marker = `Persistence Check ${Date.now()}`;
  const csvPath = path.join(os.tmpdir(), `connect-data-persistence-${Date.now()}.csv`);
  writeFileSync(csvPath, `product_name,quantity,unit_price,currency,transaction_date\n${marker},1,10.00,JOD,2026-09-27\n`);

  await page.getByRole('button', { name: /products/i }).first().click();
  await page.waitForTimeout(1000);
  assert.doesNotMatch(await page.locator('body').innerText(), new RegExp(marker), 'test marker should not pre-exist');

  await page.getByRole('button', { name: /connect data/i }).first().click();
  await page.waitForTimeout(500);
  await page.locator('input[type="file"]').setInputFiles(csvPath);
  await page.getByRole('button', { name: /prepare import/i }).click();
  await page.locator('.ceopro-toast').filter({ hasText: 'uploaded successfully' }).waitFor({ timeout: 15000 });

  await page.getByRole('button', { name: /products/i }).first().click();
  await page.waitForTimeout(1500);
  const productsText = await page.locator('body').innerText();
  assert.match(productsText, new RegExp(marker), 'newly imported product must appear on Products without a full page reload');

  console.log('PASS: a product imported via Prepare Import appears on the Products page via client-side navigation alone (no reload needed).');
}

await browser.close();
