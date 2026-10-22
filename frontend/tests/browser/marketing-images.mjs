// The Marketing Studio's image workflow in a real browser against the running
// app: create a campaign with its image in a chosen format, check the preview
// really has that shape, make a second image in another format without
// attaching it, attach it, label where it will be used, delete one, and check
// another company can't reach any of it. Fails on page errors and on any
// unexpected failed API call.
//
// Needs the app running with a language model configured (campaign copy is
// written first) and object storage. With no AI image provider configured the
// images are designed layouts; that is checked too (E2E_EXPECT_MODE).
//
//   APP_URL=http://localhost:5173 API_URL=http://localhost:8000 \
//   E2E_EMAIL=... E2E_PASSWORD=... [E2E_LOCALE=ar] [E2E_WIDTH=390] \
//   [E2E_EXPECT_MODE=designed|ai] [E2E_SHOTS=/dir] [CHROMIUM_PATH=...] \
//   node tests/browser/marketing-images.mjs
import { chromium } from 'playwright-core';

const BASE = process.env.APP_URL || 'http://localhost:5173';
const API = process.env.API_URL || 'http://localhost:8000';
const { E2E_EMAIL: email, E2E_PASSWORD: password, E2E_SHOTS: shots } = process.env;
const locale = process.env.E2E_LOCALE || 'en';
const width = Number(process.env.E2E_WIDTH || 1440);
const expectMode = process.env.E2E_EXPECT_MODE || '';
if (!email || !password) {
  console.error('Set E2E_EMAIL and E2E_PASSWORD to an account that has finished setup.');
  process.exit(2);
}

const browser = await chromium.launch(process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {});
const context = await browser.newContext({ viewport: { width, height: 900 } });
await context.addInitScript((l) => localStorage.setItem('ceopro_locale', l), locale);
const page = await context.newPage();
const problems = [];
const steps = [];
page.on('pageerror', (e) => problems.push(`page error: ${String(e).slice(0, 200)}`));
page.on('response', (r) => {
  if (r.status() >= 400 && r.url().startsWith(API)) problems.push(`${r.status()} ${r.request().method()} ${r.url().slice(API.length)}`);
});
const check = (ok, label) => {
  steps.push(`${ok ? '✓' : '✗'} ${label}`);
  if (!ok) problems.push(`failed: ${label}`);
};
const shot = async (name) => { if (shots) await page.screenshot({ path: `${shots}/${name}-${locale}-${width}.png`, fullPage: true }); };

await page.goto(`${BASE}/login`);
await page.fill('input[type="email"]', email);
await page.fill('input[type="password"]', password);
await page.click('button[type="submit"]');
await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 30000 });
const token = await page.evaluate(() => JSON.parse(localStorage.getItem('ceopro_auth_session') || '{}').accessToken);
const api = (path, init = {}) => page.request.fetch(API + path, { ...init, headers: { Authorization: `Bearer ${token}`, ...(init.headers || {}) } });

async function previewShape() {
  const img = page.locator('img.studio-image__frame').first();
  await img.waitFor({ timeout: 60000 });
  await page.waitForFunction(() => {
    const el = document.querySelector('img.studio-image__frame');
    return el && el.complete && el.naturalWidth > 0;
  }, null, { timeout: 30000 });
  return img.evaluate((el) => ({ w: el.naturalWidth, h: el.naturalHeight }));
}
const near = (shape, ratio) => Math.abs(shape.w / shape.h - ratio) / ratio <= 0.02;

// 1. A new campaign from a description, Story format, copy in the screen's language.
await page.goto(`${BASE}/marketing`);
await page.locator('[role="tablist"] button[role="tab"]').nth(2).click();
await page.locator('textarea.mk-textarea').first().fill(locale === 'ar'
  ? 'زيت زيتون بكر ممتاز من شمال الأردن، عصرة أولى على البارد، عبوة 1 لتر.'
  : 'Extra virgin olive oil from northern Jordan, first cold press, 1 litre bottle.');
await page.locator('details.studio-more summary').first().click();
await page.locator('select:has(option[value="STORY"])').first().selectOption('STORY');
await page.locator('.studio-generate button').click();
await page.locator('.studio-editor').waitFor({ timeout: 120000 });
const campaignId = new URL(page.url()).searchParams.get('campaign');
check(Boolean(campaignId), 'campaign created and opened');
const story = await previewShape();
check(near(story, 9 / 16), `story image previewed at 9:16 (${story.w}x${story.h})`);
const headline = await page.locator('.studio-post input.apex-input').first().inputValue();
check(locale === 'ar' ? /[؀-ۿ]/.test(headline) : /[A-Za-z]/.test(headline), `copy written in ${locale}: "${headline.slice(0, 40)}"`);
await page.locator('.studio-gallery__item').first().waitFor();
check(await page.locator('.studio-gallery__item').count() === 1, 'gallery shows the one image');
let assets = (await (await api(`/marketing/campaigns/${campaignId}/assets`)).json()).assets;
check(assets.length === 1 && assets[0].attached && assets[0].image_format === 'STORY', 'stored as an attached Story asset');
if (expectMode) check(assets[0].mode === expectMode, `image mode is ${expectMode} (got ${assets[0].mode})`);
await shot('marketing-story');

// 2. A landscape image for Facebook, kept in the gallery without replacing the campaign's image.
await page.locator('.studio-formats [role="radio"]').nth(3).click();
await page.locator('.studio-image__options select').first().selectOption('FACEBOOK');
const promptBox = page.locator('.studio-image__options textarea');
if (await promptBox.count()) {
  await promptBox.fill('A bottle of olive oil beside fresh bread, wide shot, warm light');
}
await page.locator('.studio-check input').uncheck();
await page.locator('.studio-image__options > button.apex-btn').click();
await page.waitForFunction(() => document.querySelectorAll('.studio-gallery__item').length === 2, null, { timeout: 120000 });
const landscape = await previewShape();
check(near(landscape, 16 / 9), `new landscape image previewed at 16:9 (${landscape.w}x${landscape.h})`);
assets = (await (await api(`/marketing/campaigns/${campaignId}/assets`)).json()).assets;
const wide = assets.find((a) => a.image_format === 'LANDSCAPE');
check(wide && !wide.attached && wide.channel === 'FACEBOOK', 'landscape kept in the gallery, not attached, labelled Facebook');
if (await promptBox.count()) check(wide?.prompt === 'A bottle of olive oil beside fresh bread, wide shot, warm light', 'edited prompt was used and stored');
await shot('marketing-gallery');

// 3. Attach it; relabel it; then delete the story image. The gallery lists
// newest first: the landscape image is the first item, the story the second.
const landscapeItem = page.locator('.studio-gallery__item').nth(0);
const storyItem = page.locator('.studio-gallery__item').nth(1);
await landscapeItem.locator('.studio-gallery__actions button.apex-btn--secondary').click();
await page.waitForFunction(() => {
  const items = document.querySelectorAll('.studio-gallery__item');
  return items.length === 2 && items[0].querySelector('.apex-pill--success') && !items[1].querySelector('.apex-pill--success');
}, null, { timeout: 30000 });
assets = (await (await api(`/marketing/campaigns/${campaignId}/assets`)).json()).assets;
check(assets.find((a) => a.image_format === 'LANDSCAPE')?.attached === true, 'landscape image attached to the campaign');
const campaign = await (await api(`/marketing/campaigns/${campaignId}`)).json();
check(campaign.image_generation_status === 'COMPLETED' && Boolean(campaign.generated_image_key), 'campaign reports its attached image');

const relabel = page.waitForResponse((r) => r.request().method() === 'PATCH' && r.url().includes('/assets/'));
await landscapeItem.locator('.studio-gallery__channel select').selectOption('INSTAGRAM');
await relabel;
assets = (await (await api(`/marketing/campaigns/${campaignId}/assets`)).json()).assets;
check(assets.find((a) => a.image_format === 'LANDSCAPE')?.channel === 'INSTAGRAM', 'channel changed from the gallery');

await storyItem.locator('.studio-gallery__actions button.apex-btn--ghost[aria-label]').click();
await storyItem.locator('button.apex-btn--danger').click();
await page.waitForFunction(() => document.querySelectorAll('.studio-gallery__item').length === 1, null, { timeout: 30000 });
assets = (await (await api(`/marketing/campaigns/${campaignId}/assets`)).json()).assets;
check(assets.length === 1 && assets[0].image_format === 'LANDSCAPE' && assets[0].attached, 'story image deleted, landscape still in use');

// 4. After a reload the gallery and the attached image are still there.
await page.reload();
await page.locator('.studio-gallery__item').first().waitFor({ timeout: 30000 });
const reloaded = await previewShape();
check(near(reloaded, 16 / 9) && await page.locator('.studio-gallery__item').count() === 1, 'gallery and attached image survive a reload');
await shot('marketing-reloaded');

// 5. Another company's session: none of it is reachable.
const otherEmail = `e2e-other+${Date.now()}@keel-sandbox.example`;
const signup = await page.request.post(`${API}/auth/signup`, { data: { full_name: 'Other Owner', business_name: 'Other Shop', email: otherEmail,
  country_code: 'JO', primary_currency: 'JOD', password: 'Other!Shop-Only-2026' } });
const otherLogin = await page.request.post(`${API}/auth/login`, { data: { email: otherEmail, password: 'Other!Shop-Only-2026' } });
const otherToken = (await otherLogin.json()).access_token;
const asOther = (path, method = 'GET') => page.request.fetch(API + path, { method, headers: { Authorization: `Bearer ${otherToken}` } });
const assetId = assets[0].asset_id;
const statuses = [
  (await asOther(`/marketing/campaigns/${campaignId}/assets`)).status(),
  (await asOther(`/marketing/campaigns/${campaignId}/assets/${assetId}/image`)).status(),
  (await asOther(`/marketing/campaigns/${campaignId}/assets/${assetId}`, 'DELETE')).status(),
];
check(signup.ok() && statuses.every((s) => s === 404), `another company gets 404 for list/stream/delete (${statuses.join(',')})`);
// These three 404s are the expected outcome, not problems.
for (let i = 0; i < 3; i += 1) {
  const index = problems.findIndex((p) => p.startsWith('404 ') && p.includes(`/marketing/campaigns/${campaignId}/assets`));
  if (index >= 0) problems.splice(index, 1);
}
check((await (await api(`/marketing/campaigns/${campaignId}/assets/${assetId}/image`)).status()) === 200, 'the owner can still read it');

// Tidy up: delete the test campaign (and its files).
check((await api(`/marketing/campaigns/${campaignId}`, { method: 'DELETE' })).ok(), 'test campaign deleted');

await browser.close();
console.log(steps.join('\n'));
if (problems.length) {
  console.error(`\n${problems.length} problem(s) (${locale}, ${width}px):\n${problems.join('\n')}`);
  process.exit(1);
}
console.log(`\nMarketing image workflow clean (${locale}, ${width}px)`);
