import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import {
  competitorDataApi, completenessTone, facetActions, facetTone, reasonKey, REASON_CODES, retryableFacets, retryOutcome, withOverview,
} from '../src/features/market-intelligence/api/competitorDataApi.js';
import httpClient from '../src/shared/lib/httpClient.js';

async function serve(t, handler) {
  const seen = [];
  const server = http.createServer((req, res) => {
    let body = '';
    req.on('data', (chunk) => { body += chunk; });
    req.on('end', () => {
      seen.push({ method: req.method, url: req.url, body: body ? JSON.parse(body) : undefined });
      res.setHeader('Content-Type', 'application/json');
      handler(req, res, body);
    });
  });
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  const original = httpClient.defaults.baseURL;
  httpClient.defaults.baseURL = `http://127.0.0.1:${server.address().port}`;
  t.after(() => { httpClient.defaults.baseURL = original; server.close(); });
  return seen;
}

test('overview, comments and retry send the real requests', async (t) => {
  const seen = await serve(t, (req, res) => {
    if (req.url.startsWith('/competitor-data/overview')) return res.end(JSON.stringify({ competitors: { c1: { rating: 4.4 } } }));
    if (req.url.startsWith('/competitors/c1/reviews')) return res.end(JSON.stringify({ comments: [{ id: 'r1', people_agreeing: 400 }], next_offset: null }));
    if (req.url.startsWith('/competitors/c1/enrich')) return res.end(JSON.stringify({ results: { PROFILE: { status: 'SUCCEEDED' } } }));
    res.statusCode = 500;
    return res.end('{}');
  });
  assert.deepEqual(await competitorDataApi.overview(), { c1: { rating: 4.4 } });
  const comments = await competitorDataApi.comments('c1', { sort: 'recent', offset: 20 });
  assert.equal(comments.comments[0].people_agreeing, 400);
  assert.ok(seen.some((r) => r.url === '/competitors/c1/reviews?sort=recent&limit=20&offset=20'));
  await competitorDataApi.retry('c1', { facets: ['PROFILE'] });
  await competitorDataApi.retry('c1', { background: true });
  const retries = seen.filter((r) => r.method === 'POST');
  assert.deepEqual(retries[0].body, { facets: ['PROFILE'] });
  assert.equal(retries[1].url, '/competitors/c1/enrich?background=true');
});

test('a competitor with no comments page reports null instead of throwing', async (t) => {
  await serve(t, (_req, res) => { res.statusCode = 404; res.end('{"detail":"Competitor not found."}'); });
  assert.equal(await competitorDataApi.comments('gone'), null);
});

test('retry all failed, price coverage, find prices and barcode use the right endpoints', async (t) => {
  const seen = await serve(t, (_req, res) => res.end('{"queued":true}'));
  await competitorDataApi.retryAllFailed();
  await competitorDataApi.findMissingPrices();
  await competitorDataApi.priceCoverage({ missingBarcode: true, limit: 50 });
  await competitorDataApi.setBarcode('p1', '3017620422003');
  await competitorDataApi.setBarcode('p1', '');
  assert.deepEqual(seen.map((r) => `${r.method} ${r.url}`), [
    'POST /competitors/enrich-failed',
    'POST /pricing/market-coverage/fill',
    'GET /pricing/market-coverage?missing_barcode=true&limit=50&offset=0',
    'PATCH /products/p1',
    'PATCH /products/p1',
  ]);
  assert.deepEqual(seen[3].body, { barcode: '3017620422003' });
  assert.deepEqual(seen[4].body, { barcode: null });  // clearing sends null, never an empty string
});

const completeness = {
  score: 40,
  facets: {
    PROFILE: { status: 'SUCCEEDED', can_retry: true },
    SOCIAL_LINKS: { status: 'FAILED', reason_code: 'NO_SOCIAL_LINKS', can_retry: true },
    REVIEWS: { status: 'BLOCKED', reason_code: 'PLATFORM_APPROVAL_MISSING', can_retry: true },
    NEWS: { status: 'SUCCEEDED', can_retry: true },
    COMMENTS: { status: 'FAILED', reason_code: 'NO_VIDEOS', can_retry: true },
    PRICES: { status: 'BLOCKED', reason_code: 'TERMS_UNREVIEWED', can_retry: false, action: 'review_source', action_source_ids: ['s1', 's2'] },
    SOCIAL_CONTENT: { status: 'BLOCKED', reason_code: 'NO_SOCIAL_LINKS', can_retry: false },
  },
};

test('only facets that are not collected and can be retried are offered for Retry', () => {
  assert.deepEqual(retryableFacets(completeness), ['SOCIAL_LINKS', 'REVIEWS', 'COMMENTS']);
  assert.deepEqual(retryableFacets(null), []);
  assert.deepEqual(retryableFacets({ facets: { PROFILE: { status: 'NOT_APPLICABLE', can_retry: false } } }), []);
});

test('a price gap that needs a terms review exposes the sources to review', () => {
  assert.deepEqual(facetActions(completeness), [{ name: 'PRICES', action: 'review_source', sourceIds: ['s1', 's2'] }]);
  assert.deepEqual(facetActions(undefined), []);
});

test('tones and reason keys are stable and unknown reasons never produce a missing translation', () => {
  assert.equal(facetTone('SUCCEEDED'), 'success');
  assert.equal(facetTone('FAILED'), 'danger');
  assert.equal(facetTone('BLOCKED'), 'warning');
  assert.equal(facetTone('PENDING'), 'neutral');
  assert.equal(completenessTone(80), 'success');
  assert.equal(completenessTone(50), 'accent');
  assert.equal(completenessTone(10), 'warning');
  assert.equal(completenessTone(null), 'neutral');
  assert.equal(reasonKey('NO_CREDENTIALS'), 'competitorData.reason.NO_CREDENTIALS');
  assert.equal(reasonKey('SOMETHING_NEW'), 'competitorData.reason.UNKNOWN');
  assert.ok(REASON_CODES.includes('PLATFORM_APPROVAL_MISSING'));
});

test('retry outcomes are summarised honestly', () => {
  assert.equal(retryOutcome({ results: { PROFILE: { status: 'SUCCEEDED' }, SOCIAL_LINKS: { status: 'SUCCEEDED' } } }), 'succeeded');
  assert.equal(retryOutcome({ results: { PROFILE: { status: 'SUCCEEDED' }, REVIEWS: { status: 'BLOCKED' } } }), 'partial');
  assert.equal(retryOutcome({ results: { PROFILE: { status: 'BLOCKED' } } }), 'failed');
  assert.equal(retryOutcome({ queued: true, already_queued: false }), 'queued');
  assert.equal(retryOutcome({ queued: false, already_queued: true }), 'alreadyQueued');
});

test('overview data is merged onto discovery rows by id', () => {
  const rows = withOverview([{ competitor_id: 'c1' }, { competitor_id: 'c2' }], { c1: { rating: 4.4 } });
  assert.deepEqual(rows.map((r) => r.data), [{ rating: 4.4 }, null]);
});

// The locale test only checks literal t('...') keys. These are built at run time, so check each family
// exists in both languages (a missing one would show its dotted name on screen).
import { readFileSync } from 'node:fs';
import { FACET_ORDER, PRICE_REASON_CODES } from '../src/features/market-intelligence/api/competitorDataApi.js';

const bundles = {
  en: JSON.parse(readFileSync(new URL('../src/assets/locales/en.json', import.meta.url), 'utf8')),
  ar: JSON.parse(readFileSync(new URL('../src/assets/locales/ar.json', import.meta.url), 'utf8')),
};
const lookup = (bundle, key) => key.split('.').reduce((value, part) => value?.[part], bundle);

test('every run-time translation key the competitor data screens build exists in English and Arabic', () => {
  const keys = [
    ...REASON_CODES.map((c) => `competitorData.reason.${c}`), 'competitorData.reason.UNKNOWN',
    ...PRICE_REASON_CODES.map((c) => `competitorData.coverage.reasons.${c}`),
    ...FACET_ORDER.map((f) => `competitorData.facet.${f}`),
    ...['SUCCEEDED', 'PARTIAL', 'FAILED', 'BLOCKED', 'PENDING', 'NOT_APPLICABLE'].map((s) => `competitorData.status.${s}`),
    ...['succeeded', 'partial', 'failed', 'queued', 'alreadyQueued', 'tooSoon', 'error'].map((o) => `competitorData.outcome.${o}`),
    ...['FOUND', 'NOTHING_FOUND', 'NOT_CONFIGURED', 'PROVIDER_ERROR'].map((o) => `competitorData.coverage.lookup.${o}`),
    ...['competitor', 'market_reference'].map((b) => `competitorData.coverage.basis.${b}`),
    ...['Positive', 'Neutral', 'Negative'].map((s) => `competitorData.overview.sentiment.${s}`),
    ...['positive', 'negative', 'neutral'].map((s) => `competitorData.comments.sentiment.${s}`),
    'competitorData.comments.helpful', 'competitorData.comments.recent',
  ];
  const missing = [];
  for (const [language, bundle] of Object.entries(bundles)) {
    for (const key of keys) if (typeof lookup(bundle, key) !== 'string') missing.push(`${language}: ${key}`);
  }
  assert.deepEqual(missing, []);
});

test('the reason codes the backend can send are all known to the screen', () => {
  // backend/src/market_scraper/competitor_enrichment.py reason constants
  const backend = ['NO_CREDENTIALS', 'CREDENTIALS_REJECTED', 'QUOTA_EXHAUSTED', 'PROVIDER_ERROR', 'NO_MATCH', 'INCOMPLETE_LISTING', 'NO_WEBSITE',
    'ROBOTS_DISALLOWED', 'SITE_UNREACHABLE', 'SHARED_RECORD', 'NO_PRODUCTS_MAPPED', 'TERMS_UNREVIEWED', 'NO_DATA_COLLECTED', 'COLLECTOR_NOT_ENABLED',
    'NO_SOCIAL_LINKS', 'NO_PLACE_ID', 'PLATFORM_APPROVAL_MISSING', 'SERVICE_MISCONFIGURED', 'NOT_ATTEMPTED', 'NO_FEED', 'NO_NEWS', 'NO_VIDEOS'];
  assert.deepEqual(backend.filter((code) => !REASON_CODES.includes(code)), []);
});
