// The Marketing Studio with the background image queue, in a real browser
// against the running app, image worker and image server: create a campaign
// (its first image is queued), wait for it to appear in the chosen format,
// queue a batch of several formats from "Make many images", follow the
// progress until every image is in the gallery, then download, attach and
// check another company can't reach them. With a real model on a CPU each
// image takes minutes; E2E_IMAGE_MINUTES sets the wait per image.
//
//   APP_URL=... API_URL=... E2E_EMAIL=... E2E_PASSWORD=... [E2E_LOCALE=ar] [E2E_WIDTH=390]
//   [E2E_IMAGE_MINUTES=6] [E2E_SHOTS=/dir] [CHROMIUM_PATH=...] node tests/browser/marketing-batch.mjs
import { chromium } from 'playwright-core';

const BASE = process.env.APP_URL || 'http://localhost:5173';
const API = process.env.API_URL || 'http://localhost:8000';
const { E2E_EMAIL: email, E2E_PASSWORD: password, E2E_SHOTS: shots } = process.env;
const locale = process.env.E2E_LOCALE || 'en';
const width = Number(process.env.E2E_WIDTH || 1440);
const perImage = Number(process.env.E2E_IMAGE_MINUTES || 6) * 60000;
if (!email || !password) {
  console.error('Set E2E_EMAIL and E2E_PASSWORD to an account that has finished setup.');
  process.exit(2);
}

const browser = await chromium.launch(process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {});
const context = await browser.newContext({ viewport: { width, height: 900 }, acceptDownloads: true });
await context.addInitScript((l) => localStorage.setItem('ceopro_locale', l), locale);
const page = await context.newPage();
const problems = [];
const steps = [];
const started = Date.now();
page.on('pageerror', (e) => problems.push(`page error: ${String(e).slice(0, 200)}`));
page.on('response', (r) => {
  if (r.status() >= 400 && r.url().startsWith(API)) problems.push(`${r.status()} ${r.request().method()} ${r.url().slice(API.length)}`);
});
const check = (ok, label) => {
  steps.push(`${ok ? '✓' : '✗'} [${Math.round((Date.now() - started) / 1000)}s] ${label}`);
  if (!ok) problems.push(`failed: ${label}`);
};
const shot = async (name) => { if (shots) await page.screenshot({ path: `${shots}/${name}-${locale}-${width}.png`, fullPage: true }); };

await page.goto(`${BASE}/login`);
await page.fill('input[type="email"]', email);
await page.fill('input[type="password"]', password);
await page.click('button[type="submit"]');
await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 30000 });
const token = await page.evaluate(() => JSON.parse(localStorage.getItem('ceopro_auth_session') || '{}').accessToken);
const api = async (path, init = {}) => (await page.request.fetch(API + path, { ...init, headers: { Authorization: `Bearer ${token}` } })).json();
const capacity = await api('/marketing/image-capacity');
check(capacity.available === true, `an image worker is live (${capacity.workers} worker(s), ${capacity.image_servers} server(s))`);

// 1. A campaign from a description; its first image (Portrait) goes through the queue.
await page.goto(`${BASE}/marketing`);
await page.locator('[role="tablist"] button[role="tab"]').nth(2).click();
await page.locator('textarea.mk-textarea').first().fill(locale === 'ar'
  ? 'خلطة زعتر بلدي 250 غرام في مرطبان زجاجي، سمسم محمّص وزعتر بري، من مخبز عائلي في عمّان.'
  : "Za'atar spice mix, 250 g glass jar, roasted sesame and wild thyme, from a family bakery in Amman.");
await page.locator('details.studio-more summary').first().click();
await page.locator('select:has(option[value="PORTRAIT"])').first().selectOption('PORTRAIT');
await page.locator('.studio-generate button').click();
await page.locator('.studio-editor').waitFor({ timeout: 15 * 60000 });
const campaignId = new URL(page.url()).searchParams.get('campaign');
check(Boolean(campaignId), 'campaign created with its copy');
const headline = await page.locator('.studio-post input.apex-input').first().inputValue();
check(locale === 'ar' ? /[؀-ۿ]/.test(headline) : /[A-Za-z]/.test(headline), `copy in ${locale}: "${headline.slice(0, 50)}"`);

async function previewShape(timeout) {
  await page.waitForFunction(() => {
    const el = document.querySelector('img.studio-image__frame');
    return el && el.complete && el.naturalWidth > 0;
  }, null, { timeout });
  return page.locator('img.studio-image__frame').first().evaluate((el) => ({ w: el.naturalWidth, h: el.naturalHeight }));
}
const first = await previewShape(perImage + 120000);
check(Math.abs(first.w / first.h - 0.8) < 0.02, `first image arrived from the queue as 4:5 (${first.w}x${first.h})`);
await shot('batch-first');

// 2. "Make many images": Square + Landscape, one each.
const panel = page.locator('.studio-batch');
await panel.waitFor({ timeout: 30000 });
const boxes = panel.locator('.studio-batch__formats input[type="checkbox"]');
for (const index of [0, 3]) if (!(await boxes.nth(index).isChecked())) await boxes.nth(index).check();
for (const index of [1, 2, 4]) if (await boxes.nth(index).isChecked()) await boxes.nth(index).uncheck();
await panel.locator('input[type="number"]').fill('1');
await panel.locator('button.apex-btn').first().click();
await panel.locator('progress').waitFor({ timeout: 30000 });
check(true, 'batch queued; progress shown');
await shot('batch-progress');
await page.waitForFunction(() => document.querySelectorAll('.studio-gallery__item').length >= 3, null, { timeout: 2 * perImage + 120000 });
const assets = (await api(`/marketing/campaigns/${campaignId}/assets`)).assets;
const formats = assets.map((a) => a.image_format).sort();
check(JSON.stringify(formats) === JSON.stringify(['LANDSCAPE', 'PORTRAIT', 'SQUARE']), `gallery holds ${formats.join(', ')}`);
check(assets.every((a) => a.mode === 'ai'), 'every image was made by the model');
const jobs = await api(`/marketing/campaigns/${campaignId}/image-jobs`);
check(jobs.counts.COMPLETED === 3 && jobs.counts.FAILED === 0, `jobs: ${JSON.stringify(jobs.counts)}`);
check(jobs.jobs.every((j) => j.seconds > 5), `real generation times: ${jobs.jobs.map((j) => `${j.image_format} ${j.seconds}s`).join(', ')}`);
await shot('batch-gallery');

// 3. Download one from the gallery and attach the landscape one.
const landscapeIndex = (await page.locator('.studio-gallery__item').evaluateAll((items) => items.map((i) => i.textContent))).findIndex((text) => /16:9/.test(text));
const item = page.locator('.studio-gallery__item').nth(landscapeIndex);
await item.locator('a[download]').waitFor({ timeout: 30000 });
const [download] = await Promise.all([page.waitForEvent('download'), item.locator('a[download]').click()]);
const file = await download.path();
const { statSync } = await import('node:fs');
check(statSync(file).size > 50000, `downloaded ${download.suggestedFilename()} (${statSync(file).size} bytes)`);
const attach = item.locator('.studio-gallery__actions button.apex-btn--secondary');
if (await attach.count()) {
  await attach.click();
  await page.waitForFunction((i) => document.querySelectorAll('.studio-gallery__item')[i]?.querySelector('.apex-pill--success'), landscapeIndex, { timeout: 30000 });
}
const campaign = await api(`/marketing/campaigns/${campaignId}`);
const attached = (await api(`/marketing/campaigns/${campaignId}/assets`)).assets.find((a) => a.attached);
check(attached?.image_format === 'LANDSCAPE' && Boolean(campaign.generated_image_key), 'landscape image attached to the campaign');

// 4. Another company can't reach the jobs or images.
const otherEmail = `e2e-other+${Date.now()}@keel-sandbox.example`;
await page.request.post(`${API}/auth/signup`, { data: { full_name: 'Other Owner', business_name: 'Other Shop', email: otherEmail,
  country_code: 'JO', primary_currency: 'JOD', password: 'Other!Shop-Only-2026' } });
const otherToken = (await (await page.request.post(`${API}/auth/login`, { data: { email: otherEmail, password: 'Other!Shop-Only-2026' } })).json()).access_token;
const asOther = async (path, method = 'GET') => (await page.request.fetch(API + path, { method, headers: { Authorization: `Bearer ${otherToken}` } })).status();
const statuses = [await asOther(`/marketing/campaigns/${campaignId}/image-jobs`), await asOther(`/marketing/campaigns/${campaignId}/assets/${attached.asset_id}/image`),
  await asOther(`/marketing/campaigns/${campaignId}/image-jobs/cancel`, 'POST')];
check(statuses.every((s) => s === 404), `another company gets 404 (${statuses.join(',')})`);
for (let i = 0; i < 3; i += 1) {
  const index = problems.findIndex((p) => p.startsWith('404 ') && p.includes(campaignId));
  if (index >= 0) problems.splice(index, 1);
}

await browser.close();
console.log(steps.join('\n'));
console.log(JSON.stringify({ campaignId, locale, width, minutes: Math.round((Date.now() - started) / 60000) }));
if (problems.length) {
  console.error(`\n${problems.length} problem(s):\n${problems.join('\n')}`);
  process.exit(1);
}
console.log(`\nQueued real-image workflow clean (${locale}, ${width}px)`);
