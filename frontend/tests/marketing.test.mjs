import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import { marketingApi } from '../src/features/marketing/api/marketingApi.js';
import httpClient, { configureHttpClientLanguage } from '../src/shared/lib/httpClient.js';

// api/marketingApi.js calls the real, mounted backend/src/ai/routers/
// marketing.py endpoints (CRUD/generation correctness of those endpoints
// themselves is covered by the backend's own pytest suite, not re-tested
// here). What's worth a local test with no backend running: that each api
// function sends the request shape the real backend actually expects and
// returns what its component consumes - same http.createServer technique
// as tests/products.test.mjs.
test('marketing api layer sends the real request shape and returns what the UI consumes', async (t) => {
  const server = http.createServer((req, res) => {
    let chunks = [];
    req.on('data', (chunk) => { chunks.push(chunk); });
    req.on('end', () => {
      const body = Buffer.concat(chunks);
      res.setHeader('Content-Type', 'application/json');

      if (req.url === '/marketing/options' && req.method === 'GET') {
        return res.end(JSON.stringify({
          strategies: { SALES_DRIVEN: 'Sales-driven copy.' },
          themes: { MINIMAL_CLEAN: 'Minimal / Clean.', CUSTOM: 'Custom.' },
        }));
      }

      if (req.url.startsWith('/marketing/campaigns?') && req.method === 'GET') {
        assert.ok(req.url.includes('limit=5'));
        return res.end(JSON.stringify({ campaigns: [{ campaign_id: 'c1', campaign_brief: 'Widget', status: 'COMPLETED' }], total: 1, limit: 5, offset: 0 }));
      }

      if (req.url === '/marketing/campaigns/c1' && req.method === 'GET') {
        return res.end(JSON.stringify({ campaign_id: 'c1', status: 'COMPLETED' }));
      }

      if (req.url === '/marketing/campaigns' && req.method === 'POST') {
        const parsed = JSON.parse(body.toString('utf8'));
        assert.deepEqual(parsed, {
          text: 'A tidy desk widget.', strategy_type: 'STORYTELLING', variants_per_platform: 2,
          creative_theme: 'MINIMAL_CLEAN',
        });
        return res.end(JSON.stringify({ campaign_id: 'c2', status: 'COMPLETED', content: {} }));
      }

      if (req.url === '/marketing/campaigns/c1/image' && req.method === 'POST') {
        const contentType = req.headers['content-type'] || '';
        assert.ok(contentType.startsWith('multipart/form-data'), 'boundary must be set by axios/FormData, not hardcoded');
        assert.ok(body.includes('photo.png'));
        return res.end(JSON.stringify({ campaign_id: 'c1', source_image_key: 't1/c1/key.png', note: 'stored, not analyzed' }));
      }

      if (req.url === '/marketing/campaigns/c1/generate-image' && req.method === 'POST') {
        return res.end(JSON.stringify({
          campaign_id: 'c1', image_generation_status: 'COMPLETED',
          image_generation_provider: 'pollinations', generated_image_key: 't1/c1/generated.png',
          image_generation_used_reference: false,
          image_generation_reference_note: 'A product reference image was provided, but this provider does not support reference-image generation.',
        }));
      }

      if (req.url === '/marketing/campaigns/c1/remove-background' && req.method === 'POST') {
        return res.end(JSON.stringify({
          campaign_id: 'c1', background_removal_status: 'COMPLETED',
          background_removal_provider: 'rembg', source_image_processed_key: 't1/c1/processed.png',
        }));
      }

      if (req.url === '/marketing/campaigns/c1/reference-selection' && req.method === 'POST') {
        const parsed = JSON.parse(body.toString('utf8'));
        assert.deepEqual(parsed, { selection: 'PROCESSED' });
        return res.end(JSON.stringify({ campaign_id: 'c1', reference_image_selection: 'PROCESSED' }));
      }

      res.statusCode = 404;
      res.end(JSON.stringify({ detail: 'not found' }));
    });
  });
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  const originalBaseURL = httpClient.defaults.baseURL;
  httpClient.defaults.baseURL = `http://127.0.0.1:${server.address().port}`;
  t.after(() => { httpClient.defaults.baseURL = originalBaseURL; server.close(); });

  const options = await marketingApi.getOptions();
  assert.deepEqual(Object.keys(options.strategies), ['SALES_DRIVEN']);
  assert.deepEqual(Object.keys(options.themes), ['MINIMAL_CLEAN', 'CUSTOM']);

  const list = await marketingApi.listCampaigns({ limit: 5 });
  assert.equal(list.total, 1);
  assert.equal(list.campaigns[0].campaign_id, 'c1');

  const one = await marketingApi.getCampaign('c1');
  assert.equal(one.status, 'COMPLETED');

  // Only fields with real values are sent - undefined/omitted optional
  // fields (url, product_id, style, tone, focus, custom_creative_prompt)
  // must never be serialized as explicit nulls the backend would reject.
  const created = await marketingApi.createCampaign({
    text: 'A tidy desk widget.', strategyType: 'STORYTELLING', variantsPerPlatform: 2, creativeTheme: 'MINIMAL_CLEAN',
  });
  assert.equal(created.campaign_id, 'c2');

  const file = new File([new Uint8Array([1, 2, 3])], 'photo.png', { type: 'image/png' });
  const uploaded = await marketingApi.uploadCampaignImage({ campaignId: 'c1', file });
  assert.equal(uploaded.source_image_key, 't1/c1/key.png');

  const generated = await marketingApi.generateImage('c1');
  assert.equal(generated.image_generation_status, 'COMPLETED');
  assert.equal(generated.image_generation_provider, 'pollinations');
  assert.equal(generated.generated_image_key, 't1/c1/generated.png');
  // Honest even on success - a reference image can be selected but still
  // not actually used by the configured provider (see image_generation.py).
  assert.equal(generated.image_generation_used_reference, false);
  assert.ok(generated.image_generation_reference_note);

  const removedBackground = await marketingApi.removeBackground('c1');
  assert.equal(removedBackground.background_removal_status, 'COMPLETED');
  assert.equal(removedBackground.background_removal_provider, 'rembg');
  assert.equal(removedBackground.source_image_processed_key, 't1/c1/processed.png');

  const selection = await marketingApi.setReferenceSelection('c1', 'PROCESSED');
  assert.equal(selection.reference_image_selection, 'PROCESSED');

  // getCampaignImage's responseType: 'blob' + URL.createObjectURL path
  // relies on the browser's real Blob/URL APIs (axios's Node adapter
  // doesn't implement responseType: 'blob' the way a browser XHR does) -
  // same known gap as ingestionApi.js::downloadTemplate's own csv/xlsx
  // path (see ingestion.test.mjs's own comment on this exact limitation),
  // so it is not exercised here; verified manually in a real browser
  // against a live backend instead.
});

test('studio calls: one press = one request key, the campaign language, edits and deletion', async (t) => {
  const seen = [];
  const server = http.createServer((req, res) => {
    const chunks = [];
    req.on('data', (chunk) => chunks.push(chunk));
    req.on('end', () => {
      const body = chunks.length ? JSON.parse(Buffer.concat(chunks).toString('utf8')) : null;
      seen.push({ method: req.method, url: req.url, body, language: req.headers['x-app-language'] });
      res.setHeader('Content-Type', 'application/json');
      res.end(JSON.stringify({ campaign_id: 'c9', status: 'COMPLETED', deleted: req.method === 'DELETE' }));
    });
  });
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  const originalBaseURL = httpClient.defaults.baseURL;
  httpClient.defaults.baseURL = `http://127.0.0.1:${server.address().port}`;
  t.after(() => { httpClient.defaults.baseURL = originalBaseURL; server.close(); });

  // The screen is in English; the campaign is asked for in Arabic and must stay Arabic.
  configureHttpClientLanguage(() => 'en');
  t.after(() => configureHttpClientLanguage(null));
  await marketingApi.createCampaign({ productId: 'p1', strategyType: 'SALES_DRIVEN', requestKey: 'press0001', generateImage: true, language: 'ar' });
  await marketingApi.updateCampaign('c9', { title: 'Weekend offer', variants: [{ platform: 'INSTAGRAM', variant_index: 1, body_copy: 'New caption' }] });
  await marketingApi.deleteCampaign('c9');
  await marketingApi.listCampaigns({ limit: 8, offset: 16, q: 'kunafa' });

  assert.deepEqual(seen[0], {
    method: 'POST', url: '/marketing/campaigns', language: 'ar',
    body: { product_id: 'p1', strategy_type: 'SALES_DRIVEN', request_key: 'press0001', generate_image: true },
  });
  assert.deepEqual(seen[1].body, { title: 'Weekend offer', variants: [{ platform: 'INSTAGRAM', variant_index: 1, body_copy: 'New caption' }] });
  assert.equal(seen[1].method, 'PATCH');
  assert.deepEqual([seen[2].method, seen[2].url], ['DELETE', '/marketing/campaigns/c9']);
  assert.equal(seen[1].language, 'en', 'other requests follow the screen language');
  assert.equal(seen[3].url, '/marketing/campaigns?limit=8&offset=16&q=kunafa');
});

test('image gallery api calls send the backend request shapes', async (t) => {
  const seen = [];
  const server = http.createServer((req, res) => {
    const chunks = [];
    req.on('data', (chunk) => chunks.push(chunk));
    req.on('end', () => {
      const raw = Buffer.concat(chunks).toString('utf8');
      seen.push({ method: req.method, url: req.url, body: raw ? JSON.parse(raw) : null });
      res.setHeader('Content-Type', 'application/json');
      if (req.url === '/marketing/campaigns/c1/assets' && req.method === 'GET') {
        return res.end(JSON.stringify({ campaign_id: 'c1', assets: [{ asset_id: 'a1', image_format: 'STORY', attached: true }] }));
      }
      if (req.url === '/marketing/campaigns/c1/assets/a1/image') {
        res.setHeader('Content-Type', 'image/png');
        return res.end(Buffer.from([0x89, 0x50, 0x4e, 0x47]));
      }
      return res.end(JSON.stringify({ ok: true, asset: { asset_id: 'a2' } }));
    });
  });
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  t.after(() => server.close());
  const previous = httpClient.defaults.baseURL;
  httpClient.defaults.baseURL = `http://127.0.0.1:${server.address().port}`;
  t.after(() => { httpClient.defaults.baseURL = previous; });

  await marketingApi.generateImage('c1');
  await marketingApi.generateImage('c1', { imageFormat: 'STORY', prompt: '  a cake  ', channel: 'TIKTOK', attach: false });
  assert.deepEqual(seen[0], { method: 'POST', url: '/marketing/campaigns/c1/generate-image', body: null });
  assert.deepEqual(seen[1].body, { image_format: 'STORY', prompt: 'a cake', channel: 'TIKTOK', attach: false });

  const listed = await marketingApi.listAssets('c1');
  assert.equal(listed.assets[0].image_format, 'STORY');
  const blob = await marketingApi.getAssetImageBlob('c1', 'a1');
  assert.ok(blob);

  await marketingApi.updateAsset('c1', 'a1', { attach: true, channel: 'INSTAGRAM' });
  await marketingApi.updateAsset('c1', 'a1', { channel: null });
  await marketingApi.deleteAsset('c1', 'a1');
  const [attach, clear, remove] = seen.slice(-3);
  assert.deepEqual(attach, { method: 'PATCH', url: '/marketing/campaigns/c1/assets/a1', body: { attach: true, channel: 'INSTAGRAM' } });
  assert.deepEqual(clear.body, { clear_channel: true });
  assert.deepEqual([remove.method, remove.url], ['DELETE', '/marketing/campaigns/c1/assets/a1']);

  await marketingApi.createCampaign({ text: 'Cake', generateImage: true, imageFormat: 'PORTRAIT' });
  assert.equal(seen.at(-1).body.image_format, 'PORTRAIT');
  await marketingApi.createCampaign({ text: 'Cake', imageFormat: 'PORTRAIT' });
  assert.equal(seen.at(-1).body.image_format, undefined); // no image asked for: no format sent
});

test('image batch api calls send the backend request shapes', async (t) => {
  const seen = [];
  const server = http.createServer((req, res) => {
    const chunks = [];
    req.on('data', (c) => chunks.push(c));
    req.on('end', () => {
      const raw = Buffer.concat(chunks).toString('utf8');
      seen.push({ method: req.method, url: req.url, body: raw ? JSON.parse(raw) : null });
      res.setHeader('Content-Type', 'application/json');
      res.end(JSON.stringify({ ok: true, counts: { QUEUED: 1, RUNNING: 0, COMPLETED: 0, FAILED: 0, CANCELLED: 0 }, jobs: [] }));
    });
  });
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  t.after(() => server.close());
  const previous = httpClient.defaults.baseURL;
  httpClient.defaults.baseURL = `http://127.0.0.1:${server.address().port}`;
  t.after(() => { httpClient.defaults.baseURL = previous; });

  await marketingApi.queueImageBatch('c1', { formats: ['SQUARE', 'STORY'], variations: 3, prompt: ' cake ', channel: 'TIKTOK', attachFirst: true });
  await marketingApi.queueImageBatch('c1', { formats: ['WIDE'] });
  await marketingApi.listImageJobs('c1');
  await marketingApi.cancelImageJobs('c1');
  await marketingApi.retryImageJobs('c1');
  await marketingApi.getImageCapacity();
  assert.deepEqual(seen[0], { method: 'POST', url: '/marketing/campaigns/c1/image-batches',
    body: { formats: ['SQUARE', 'STORY'], variations: 3, prompt: 'cake', channel: 'TIKTOK', attach_first: true } });
  assert.deepEqual(seen[1].body, { formats: ['WIDE'], variations: 1 });
  assert.deepEqual(seen.slice(2).map((r) => `${r.method} ${r.url}`), [
    'GET /marketing/campaigns/c1/image-jobs?limit=50', 'POST /marketing/campaigns/c1/image-jobs/cancel',
    'POST /marketing/campaigns/c1/image-jobs/retry', 'GET /marketing/image-capacity',
  ]);
});
