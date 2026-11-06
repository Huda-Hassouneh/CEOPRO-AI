// The Marketing Studio's one-screen flows in a real browser, on the
// production page and styles (tests/browser/marketing-studio.html), with the
// Marketing API answered by a stateful fake (marketing-fake-api.mjs). Checks
// what an owner sees and what the page really sends: one tap on a product
// then "Create post" with every default (Customize never opened), a link or
// a description typed into the same box, every Customize setting, the post
// preview, copy and download, changing the text, a different picture, the
// picture list, new text, recent posts and the full list, a Google ad,
// phone width without sideways scrolling, Arabic right-to-left, and an
// axe-core WCAG 2.1 AA audit of each screen.
//
// It does NOT exercise the backend, a language model or an image service:
// marketing-images.mjs does that against the running app.
//
//   (in frontend/) npx vite --port 5179 &
//   APP_URL=http://localhost:5179 [CHROMIUM_PATH=...] [E2E_SHOTS=/dir] [E2E_IMAGES=/dir] node tests/browser/marketing-studio-ui.mjs
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { chromium } from 'playwright-core';
import { installFakeApi, sampleCampaign } from './marketing-fake-api.mjs';

const require = createRequire(import.meta.url);
const AXE = readFileSync(require.resolve('axe-core/axe.min.js'), 'utf8');
const BASE = `${process.env.APP_URL || 'http://localhost:5179'}/tests/browser/marketing-studio.html`;
const shots = process.env.E2E_SHOTS;
const images = process.env.E2E_IMAGES;
const en = JSON.parse(readFileSync(new URL('../../src/assets/locales/en.json', import.meta.url), 'utf8'));
const ar = JSON.parse(readFileSync(new URL('../../src/assets/locales/ar.json', import.meta.url), 'utf8'));

const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH || undefined, args: ['--no-sandbox'] });
const results = [];
const step = async (label, fn) => {
  try { await fn(); results.push(`✓ ${label}`); } catch (err) { results.push(`✗ ${label}\n    ${String(err.message).split('\n').slice(0, 4).join('\n    ')}`); }
};

async function newPage({ width = 1366, locale = 'en', campaigns = [], url = BASE, aiImages = true } = {}) {
  const context = await browser.newContext({ viewport: { width, height: 900 }, permissions: ['clipboard-read', 'clipboard-write'], acceptDownloads: true });
  await context.addInitScript((l) => localStorage.setItem('ceopro_locale', l), locale);
  const page = await context.newPage();
  page.setDefaultTimeout(8000);
  const errors = [];
  page.on('pageerror', (e) => errors.push(String(e)));
  const api = await installFakeApi(page, { images, campaigns, aiImages });
  await page.goto(url);
  await page.locator('.studio-one').waitFor();
  return { page, api, errors, context };
}

async function axe(page, where) {
  await page.addScriptTag({ content: AXE });
  const violations = await page.evaluate(async () => (await window.axe.run(document.querySelector('.studio-page'), {
    runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'] }, resultTypes: ['violations'],
  })).violations.map((v) => `${v.id}: ${v.nodes.slice(0, 2).map((n) => n.target.join(' ')).join(', ')}`));
  assert.deepEqual(violations, [], `accessibility problems on ${where}: ${violations.join(' | ')}`);
}

const noSideScroll = (page) => page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
const lastRequest = (api, method, pattern) => [...api.requests].reverse().find((r) => r.method === method && pattern.test(r.path));
const creates = (api) => api.requests.filter((r) => r.method === 'POST' && r.path === '/marketing/campaigns');
const s = en.studio;
const createButton = (page, t = s) => page.getByRole('button', { name: t.one.create, exact: true });

// 1. The whole job in two taps: pick a product, press Create post. Customize is never opened.
await step('one screen: pick a product, Create post, every default; Customize stays closed', async () => {
  const { page, api, errors, context } = await newPage();
  await page.getByRole('heading', { name: s.one.title }).waitFor();
  await page.getByRole('heading', { name: s.one.emptyTitle }).waitFor();
  assert.equal(await page.locator('details.studio-customize[open]').count(), 0, 'Customize is closed by default');
  assert.equal(await page.locator('.studio-defaults').textContent(), 'Instagram post · Sell more · English · Square', 'defaults shown as one line');
  await axe(page, 'empty screen');
  if (shots) await page.screenshot({ path: `${shots}/one-open.png`, fullPage: true });

  await createButton(page).click();
  await page.getByText(s.one.usingNone).waitFor();
  assert.equal(creates(api).length, 0, 'nothing is sent without a product, link or description');

  await page.locator('.studio-what__products .apex-chip', { hasText: 'Olive oil 1L' }).click();
  await page.getByText('Using your product: Olive oil 1L').waitFor();
  await createButton(page).click();
  await page.getByRole('heading', { name: s.result.readyTitle }).waitFor();

  const create = creates(api).at(-1);
  assert.equal(create.body.product_id, 'p1');
  assert.equal(create.body.strategy_type, 'SALES_DRIVEN');
  assert.deepEqual(create.body.platforms, ['INSTAGRAM']);
  assert.equal(create.body.image_format, 'SQUARE');
  assert.equal(create.body.generate_image, true);
  assert.equal(create.body.variants_per_platform, 1);
  assert.equal(create.body.tone, undefined, 'tone left to KEEL by default');
  assert.equal(create.body.custom_creative_prompt, undefined, 'no extra instructions by default');
  assert.equal(create.headers['x-app-language'], 'en');
  assert.ok(create.body.request_key);
  assert.equal(await page.locator('details.studio-customize[open]').count(), 0, 'still closed after creating');
  assert.ok((await page.locator('.studio-preview__who small').textContent()).includes('Instagram'));
  assert.equal(await page.locator('.studio-recent__item.is-open').count(), 1, 'the new post is listed and marked in Recent posts');
  await axe(page, 'result');
  if (shots) await page.screenshot({ path: `${shots}/one-result.png`, fullPage: true });
  assert.deepEqual(errors, []);
  await context.close();
});

// 2. The same box takes a link or a description.
await step('one box: a link or a description is used when no product is picked', async () => {
  const { page, api, errors, context } = await newPage();
  const box = page.locator('#studio-what-input');
  await box.fill('https://shop.example.com/olive-oil');
  await page.getByText('Using the page at shop.example.com/olive-oil').waitFor();
  assert.equal(await page.locator('.studio-what__products').count(), 0, 'no product suggestions for a link');
  await createButton(page).click();
  await page.getByRole('heading', { name: s.result.readyTitle }).waitFor();
  assert.equal(creates(api).at(-1).body.url, 'https://shop.example.com/olive-oil');

  await page.locator('#studio-what-input').fill('Hand-made olive oil soap, lavender scent, 100 g bar');
  await page.getByText(s.one.usingDescribe).waitFor();
  await page.locator('#studio-what-input').press('Enter');
  await page.waitForFunction(() => document.querySelectorAll('.studio-recent__item').length >= 2);
  const create = creates(api).at(-1);
  assert.equal(create.body.text, 'Hand-made olive oil soap, lavender scent, 100 g bar', 'Enter creates the post too');
  assert.equal(create.body.product_id, undefined);
  assert.deepEqual(errors, []);
  await context.close();
});

// 3. Every setting under Customize reaches the request; the picture shape follows the platform unless chosen.
await step('Customize: platform, goal, occasion, audience, tone, language, shape, style, notes', async () => {
  const { page, api, errors, context } = await newPage();
  await page.locator('.studio-what__products .apex-chip').first().click();
  await page.locator('summary', { hasText: s.one.customize }).click();
  await axe(page, 'customize open');
  await page.getByLabel(s.one.where, { exact: true }).selectOption('tiktok');
  assert.match(await page.locator('.studio-defaults').textContent(), /TikTok · Sell more · English · Full screen/, 'shape follows the platform');
  await page.getByLabel(s.one.goal, { exact: true }).selectOption('seasonal');
  await page.getByLabel(s.one.occasion, { exact: true }).selectOption('ramadan');
  await page.getByLabel(s.one.who, { exact: true }).selectOption('custom');
  await page.getByLabel(s.wizard.customAudience).fill('Coffee shop owners');
  await page.getByLabel(s.one.tone, { exact: true }).selectOption('friendly');
  await page.getByLabel(s.one.language, { exact: true }).selectOption('ar');
  await page.getByLabel(s.one.style, { exact: true }).selectOption('LIFESTYLE');
  await page.getByLabel(s.wizard.notesLabel).fill('Free delivery in Amman');
  if (shots) await page.screenshot({ path: `${shots}/one-customize.png`, fullPage: true });
  await createButton(page).click();
  await page.getByRole('heading', { name: s.result.readyTitle }).waitFor();
  let create = creates(api).at(-1);
  assert.deepEqual(create.body.platforms, ['TIKTOK']);
  assert.equal(create.body.image_format, 'STORY');
  assert.equal(create.body.strategy_type, 'STORYTELLING');
  assert.equal(create.body.creative_theme, 'LIFESTYLE');
  assert.equal(create.body.tone, 'Friendly');
  assert.equal(create.headers['x-app-language'], 'ar');
  assert.match(create.body.custom_creative_prompt, /Audience: Coffee shop owners\./);
  assert.match(create.body.custom_creative_prompt, /Occasion: Ramadan\./);
  assert.match(create.body.custom_creative_prompt, /Free delivery in Amman/);

  await page.getByLabel(s.one.shape, { exact: true }).selectOption('WIDE');
  await createButton(page).click();
  await page.waitForFunction(() => document.querySelectorAll('.studio-recent__item').length >= 2);
  create = creates(api).at(-1);
  assert.equal(create.body.image_format, 'WIDE', 'a chosen shape wins over the platform default');
  assert.notEqual(create.body.request_key, creates(api).at(-2).body.request_key, 'a changed setting is a new request');
  assert.deepEqual(errors, []);
  await context.close();
});

// 4. Using the post: copy, download, change the text, a different picture, the picture list, new text.
await step('result: copy text, download, change and save the text, undo, new picture, picture list, new text', async () => {
  const { page, api, errors, context } = await newPage({ campaigns: [sampleCampaign('c-one', ['SQUARE'])], url: `${BASE}?campaign=c-one` });
  await page.getByRole('heading', { name: s.result.readyTitle }).waitFor();

  await page.getByRole('button', { name: s.result.copyText }).click();
  await page.getByRole('button', { name: s.result.copied }).waitFor();
  assert.equal(await page.evaluate(() => navigator.clipboard.readText()),
    'Taste the north of Jordan\n\nFirst cold press, straight from our family groves.\nOne litre of pure, golden flavour for every meal.\n\n#OliveOil #MadeInJordan #HealthyKitchen\n\nOrder today');

  const download = page.getByRole('link', { name: s.result.download });
  await download.waitFor();
  assert.match(await download.getAttribute('download'), /^keel-Cold-pressed-olive-oil-square-[a-z0-9]{8}\.png$/);
  const [file] = await Promise.all([page.waitForEvent('download'), download.click()]);
  assert.ok(file.suggestedFilename().endsWith('.png'), 'the picture downloads');

  await page.getByRole('button', { name: s.result.editText }).click();
  const title = page.getByLabel(s.result.headline);
  await title.fill('Pure gold from Jordan');
  assert.equal(await page.locator('.studio-preview .studio-post__headline').textContent(), 'Pure gold from Jordan', 'preview updates while typing');
  await page.getByRole('button', { name: s.result.undo }).click();
  assert.equal(await title.inputValue(), 'Taste the north of Jordan', 'undo restores the text');
  await title.fill('Pure gold from Jordan');
  await page.getByLabel(s.result.hashtags).fill('oliveoil  jordan');
  await axe(page, 'change the text');
  await page.getByRole('button', { name: s.result.save }).click();
  await page.getByRole('heading', { name: s.result.nextTitle }).waitFor();
  assert.deepEqual(lastRequest(api, 'PATCH', /^\/marketing\/campaigns\/c-one$/).body.variants,
    [{ platform: 'INSTAGRAM', variant_index: 1, headline: 'Pure gold from Jordan', hashtags: ['#oliveoil', '#jordan'] }]);

  await page.getByRole('button', { name: s.result.newPicture }).click();
  assert.equal(await page.getByRole('radio', { name: new RegExp(s.formatsPlain.SQUARE.title) }).getAttribute('aria-checked'), 'true');
  await axe(page, 'try a different picture');
  await page.getByRole('radio', { name: new RegExp(s.formatsPlain.WIDE.title) }).click();
  await page.getByLabel(s.result.describe).fill('Olive oil and bread, wide shot');
  await page.getByLabel(s.result.useNew).uncheck();
  await page.getByRole('button', { name: s.result.makePicture }).click();
  await page.locator('.studio-gallery[open] .studio-gallery__item').nth(1).waitFor();
  assert.deepEqual(lastRequest(api, 'POST', /\/generate-image$/).body, { image_format: 'WIDE', prompt: 'Olive oil and bread, wide shot', attach: false });

  const wide = page.locator('.studio-gallery__item').filter({ hasText: s.formatsPlain.WIDE.title });
  await wide.getByRole('button', { name: s.result.usePicture }).click();
  await wide.getByText(s.result.inUse).waitFor();
  await wide.locator('.studio-gallery__channel select').selectOption('FACEBOOK');
  await page.waitForTimeout(200);
  assert.equal(lastRequest(api, 'PATCH', /\/assets\//).body.channel, 'FACEBOOK');
  const squareItem = page.locator('.studio-gallery__item').filter({ hasText: s.formatsPlain.SQUARE.title });
  await squareItem.getByRole('button', { name: s.gallery.deleteNamed.replace('{{format}}', s.formatsPlain.SQUARE.title) }).click();
  await squareItem.getByRole('button', { name: s.gallery.confirmDelete }).click();
  await page.waitForFunction(() => document.querySelectorAll('.studio-gallery__item').length === 1);

  await page.getByRole('button', { name: s.result.newText }).click();
  await page.waitForFunction(() => document.querySelectorAll('.studio-recent__item').length >= 2);
  const rewrite = lastRequest(api, 'POST', /^\/marketing\/campaigns$/);
  assert.deepEqual(rewrite.body.platforms, ['INSTAGRAM']);
  assert.equal(rewrite.body.image_format, 'SQUARE');
  assert.deepEqual(errors, []);
  await context.close();
});

// 5. Recent posts and the full list: open, search, delete.
await step('recent posts and the full list: open, search, delete', async () => {
  const { page, api, errors, context } = await newPage({ campaigns: [sampleCampaign('c-a'), { ...sampleCampaign('c-b'), campaign_brief: 'Honey jar' }] });
  await page.locator('.studio-recent__item').nth(1).waitFor();
  await page.locator('.studio-recent__item', { hasText: 'Honey jar' }).click();
  await page.getByRole('heading', { name: s.result.readyTitle }).waitFor();
  await page.getByRole('button', { name: s.one.seeAll }).click();
  await page.locator('.studio-all .studio-history li').nth(1).waitFor();
  await axe(page, 'full list');
  await page.getByRole('searchbox', { name: s.searchHistory }).fill('honey');
  await page.waitForFunction(() => document.querySelectorAll('.studio-all .studio-history li').length === 1);
  await page.getByRole('searchbox', { name: s.searchHistory }).fill('');
  await page.locator('.studio-all .studio-history li').nth(1).waitFor();
  await page.getByRole('button', { name: s.deleteNamed.replace('{{title}}', 'Honey jar') }).click();
  await page.getByRole('button', { name: s.confirmDelete }).click();
  await page.waitForFunction(() => document.querySelectorAll('.studio-all .studio-history li').length === 1);
  assert.ok(lastRequest(api, 'DELETE', /^\/marketing\/campaigns\/c-b$/));
  await page.getByRole('heading', { name: s.one.emptyTitle }).waitFor();
  assert.deepEqual(errors, []);
  await context.close();
});

// 6. A Google ad from a product preselected with ?product=.
await step('Google ad from a preselected product: ad preview and text limits', async () => {
  const { page, api, errors, context } = await newPage({ url: `${BASE}?product=p1` });
  await page.getByText('Using your product: Olive oil 1L').waitFor();
  await page.locator('summary', { hasText: s.one.customize }).click();
  await page.getByLabel(s.one.where, { exact: true }).selectOption('google');
  await createButton(page).click();
  await page.locator('.studio-preview--ad').waitFor();
  const create = creates(api).at(-1);
  assert.deepEqual(create.body.platforms, ['GOOGLE_ADS']);
  assert.equal(create.body.image_format, 'WIDE');
  await page.getByRole('button', { name: s.result.editText }).click();
  await page.getByText('8 characters left').waitFor();
  assert.equal(await page.getByLabel(s.result.hashtags).count(), 0, 'ads have no hashtags');
  await axe(page, 'Google ad');
  assert.deepEqual(errors, []);
  await context.close();
});

// 7. Phone width, English and Arabic: no sideways scrolling, RTL, the result is brought into view.
for (const locale of ['en', 'ar']) {
  await step(`phone width (390px, ${locale}): fits, RTL in Arabic, result scrolled into view`, async () => {
    const t = (locale === 'ar' ? ar : en).studio;
    const { page, errors, context } = await newPage({ width: 390, locale });
    assert.equal(await page.locator('.studio-page').getAttribute('dir'), locale === 'ar' ? 'rtl' : 'ltr');
    assert.ok(await noSideScroll(page) <= 0, 'no sideways scroll when opened');
    await page.locator('.studio-what__products .apex-chip').first().click();
    await page.locator('summary', { hasText: t.one.customize }).click();
    assert.ok(await noSideScroll(page) <= 0, 'no sideways scroll with Customize open');
    await page.locator('summary', { hasText: t.one.customize }).click();
    await createButton(page, t).click();
    await page.getByRole('heading', { name: t.result.readyTitle }).waitFor();
    await page.waitForTimeout(800);
    const inView = await page.evaluate(() => { const r = document.querySelector('.studio-editor').getBoundingClientRect(); return r.top < window.innerHeight && r.bottom > 0; });
    assert.ok(inView, 'the new post is scrolled into view');
    assert.ok(await noSideScroll(page) <= 0, 'no sideways scroll on the result');
    await axe(page, `phone result (${locale})`);
    if (shots) await page.screenshot({ path: `${shots}/one-phone-${locale}.png`, fullPage: true });
    assert.deepEqual(errors, []);
    await context.close();
  });
}

// 8. When only text layouts can be made, it is said plainly and nothing claims an outside service.
await step('no photo-style pictures available: plain explanation, still creates', async () => {
  const { page, context } = await newPage({ aiImages: false });
  assert.equal(await page.getByText(s.wizard.privacy).count(), 0, 'no outside-service note when nothing is sent out');
  await page.locator('.studio-what__products .apex-chip').first().click();
  await createButton(page).click();
  await page.getByRole('button', { name: s.result.newPicture }).click();
  await page.getByText(s.result.layoutOnly).waitFor();
  await context.close();
});

await browser.close();
console.log(results.join('\n'));
const failed = results.filter((r) => r.startsWith('✗')).length;
console.log(`\n${results.length - failed} passed, ${failed} failed`);
process.exit(failed ? 1 : 0);
