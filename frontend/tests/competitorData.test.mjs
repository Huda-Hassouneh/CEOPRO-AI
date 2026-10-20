import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import {
  canReviewPrices, competitorDataApi, completenessTone, facetActions, facetGaps, facetNextStep, facetsWorthRetrying, facetTone, nextStepKey, retryFindings, intelChannel, intelOrigin, needsCheck, onRequestAction,
  parseCorrectedPrice, reasonKey, REASON_CODES, RETRYABLE_FACETS, retryableFacets, retryOutcome, withOverview,
} from '../src/features/market-intelligence/api/competitorDataApi.js';
import { discoveryApi } from '../src/features/market-intelligence/api/discoveryApi.js';
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

// ---- retry with depth, on-request facets, and the owner's check of a price ----

test('retry sends depth only when it is not the default, and the background flag as a query', async (t) => {
  const seen = await serve(t, (_req, res) => res.end('{"queued":true}'));
  await competitorDataApi.retry('c1', { facets: ['PRICES'], depth: 'deep', background: true });
  await competitorDataApi.retry('c1', { facets: ['PRICES'] });
  await competitorDataApi.retry('c1');
  assert.deepEqual(seen.map((r) => [r.url, r.body]), [
    ['/competitors/c1/enrich?background=true', { facets: ['PRICES'], depth: 'deep' }],
    ['/competitors/c1/enrich', { facets: ['PRICES'] }],
    ['/competitors/c1/enrich', undefined],
  ]);
});

test('the owner\'s check of a price posts the decision to the review endpoint', async (t) => {
  const seen = await serve(t, (_req, res) => res.end('{"verdict":"CORRECTED"}'));
  await discoveryApi.reviewIntel('c1', { intelId: 'i1', verdict: 'CORRECTED', correctedPrice: 11.5, currency: 'JOD' });
  await discoveryApi.reviewIntel('c1', { intelId: 'i1', verdict: 'CLEARED' });
  assert.equal(seen[0].method, 'POST');
  assert.equal(seen[0].url, '/discovery/competitors/c1/intel/review');
  assert.deepEqual(seen[0].body, { intel_id: 'i1', verdict: 'CORRECTED', corrected_price: 11.5, currency: 'JOD' });
  assert.deepEqual(seen[1].body, { intel_id: 'i1', verdict: 'CLEARED' });
});

test('PRICES and SOCIAL_CONTENT get their own buttons, and "load more" only once something was collected', () => {
  const facets = (prices, social) => ({ facets: { PRICES: prices, SOCIAL_CONTENT: social, PROFILE: { can_retry: true, status: 'FAILED' } } });
  assert.deepEqual(onRequestAction(facets({ can_retry: true, status: 'SUCCEEDED' }), 'PRICES'), { canRun: true, canLoadMore: true, hasData: true });
  assert.deepEqual(onRequestAction(facets({ can_retry: true, status: 'FAILED' }), 'PRICES'), { canRun: true, canLoadMore: false, hasData: false });
  assert.equal(onRequestAction(facets({ can_retry: false, status: 'NOT_APPLICABLE' }), 'PRICES'), null);
  assert.equal(onRequestAction(facets({}, { can_retry: true, status: 'PENDING' }), 'SOCIAL_CONTENT').canRun, true);
  assert.equal(onRequestAction(facets({}, {}), 'PROFILE'), null); // not an on-request facet
  assert.equal(onRequestAction(null, 'PRICES'), null);
  // The plain Retry never names the on-request facets.
  assert.ok(!RETRYABLE_FACETS.includes('PRICES') && !RETRYABLE_FACETS.includes('SOCIAL_CONTENT'));
  assert.deepEqual(retryableFacets(facets({ can_retry: true, status: 'FAILED' }, {})), ['PROFILE']);
});

test('the new price and social reasons have translations keys, unknown ones fall back', () => {
  for (const code of ['NO_PRICES_PUBLISHED', 'JS_RENDERED', 'OCR_NOT_AVAILABLE', 'NOT_OWN_SITE', 'NO_POSTS']) {
    assert.ok(REASON_CODES.includes(code));
    assert.equal(reasonKey(code), `competitorData.reason.${code}`);
  }
  assert.equal(reasonKey('SOMETHING_NEW'), 'competitorData.reason.UNKNOWN');
});

test('only an owner or admin is offered the price check', () => {
  assert.equal(canReviewPrices(['owner']), true);
  assert.equal(canReviewPrices([' Admin ']), true);
  assert.equal(canReviewPrices(['manager', 'staff']), false);
  assert.equal(canReviewPrices(undefined), false);
});

test('a price fact says how it was read and whether it needs a look', () => {
  assert.equal(intelOrigin({}), 'page');
  assert.equal(intelOrigin({ extracted_by: 'ocr' }), 'ocr');
  assert.equal(intelOrigin({ extracted_by: 'something-else' }), 'page');
  assert.equal(needsCheck({ extracted_by: 'ocr' }), true);
  assert.equal(needsCheck({ extracted_by: 'caption' }), true);
  assert.equal(needsCheck({ extracted_by: 'pdf_text' }), false); // a PDF's own text layer is not a guess
  assert.equal(needsCheck({ extracted_by: 'vision', verified: true }), false);
  assert.equal(needsCheck({}), false);
  assert.equal(intelChannel({ channel: 'instagram' }), 'instagram');
  assert.equal(intelChannel({ channel: 'website' }), null);
  assert.equal(intelChannel({}), null);
});

test('a corrected price must be a plain number; Arabic digits and a decimal comma are accepted', () => {
  assert.equal(parseCorrectedPrice('3.50'), 3.5);
  assert.equal(parseCorrectedPrice(' 12 '), 12);
  assert.equal(parseCorrectedPrice('3,5'), 3.5);
  assert.equal(parseCorrectedPrice('٣٫٥'.replace('٫', '.')), 3.5);
  for (const bad of ['', 'abc', '-1', '1.23456', '3 JD', null, undefined, '1e3']) assert.equal(parseCorrectedPrice(bad), null, String(bad));
});


test('every gap carries its reason, detail and who can fix it', () => {
  const completeness = { facets: {
    PROFILE: { status: 'SUCCEEDED', can_retry: true },
    COMMENTS: { status: 'BLOCKED', reason_code: 'NO_CREDENTIALS', reason_detail: 'YOUTUBE_API_KEY is not set.', can_retry: true, next_step: 'admin' },
    NEWS: { status: 'FAILED', reason_code: 'NO_NEWS', can_retry: true },
    SOCIAL_LINKS: { status: 'NOT_APPLICABLE', reason_code: 'NO_WEBSITE', can_retry: false },
  } };
  assert.deepEqual(facetGaps(completeness), [
    { name: 'NEWS', status: 'FAILED', reasonCode: 'NO_NEWS', detail: null, nextStep: 'retry' },
    { name: 'COMMENTS', status: 'BLOCKED', reasonCode: 'NO_CREDENTIALS', detail: 'YOUTUBE_API_KEY is not set.', nextStep: 'admin' },
  ]);
  assert.deepEqual(facetGaps(null), []);
});

test('next step falls back sensibly for a server that does not send it yet', () => {
  assert.equal(facetNextStep({ status: 'FAILED', can_retry: true }), 'retry');
  assert.equal(facetNextStep({ status: 'FAILED', can_retry: false }), 'none');
  assert.equal(facetNextStep({ status: 'SUCCEEDED', can_retry: true }), 'none');
  assert.equal(facetNextStep({ status: 'BLOCKED', next_step: 'wait' }), 'wait');
  assert.equal(nextStepKey('admin'), 'competitorData.nextStep.admin');
  assert.equal(nextStepKey('surprise'), 'competitorData.nextStep.retry');
});

test('a retry reports the reason for each facet that did not succeed, not the throttled ones', () => {
  const response = { results: {
    PROFILE: { status: 'SUCCEEDED' },
    COMMENTS: { status: 'BLOCKED', reason_code: 'NO_CREDENTIALS', reason_detail: 'YOUTUBE_API_KEY is not set.', next_step: 'admin' },
    NEWS: { status: 'THROTTLED', retry_after_seconds: 12 },
  } };
  assert.deepEqual(retryFindings(response), [
    { name: 'COMMENTS', status: 'BLOCKED', reasonCode: 'NO_CREDENTIALS', detail: 'YOUTUBE_API_KEY is not set.', nextStep: 'admin' },
  ]);
  assert.deepEqual(retryFindings(undefined), []);
});

test('the comments request sends the sentiment filter only when one is chosen', async (t) => {
  const seen = await serve(t, (_req, res) => res.end('{"comments":[],"next_offset":null}'));
  await competitorDataApi.comments('c1', { sentiment: 'negative' });
  await competitorDataApi.comments('c1');
  assert.equal(seen[0].url, '/competitors/c1/reviews?sort=helpful&limit=20&offset=0&sentiment=negative');
  assert.equal(seen[1].url, '/competitors/c1/reviews?sort=helpful&limit=20&offset=0');
});

test('a plain retry skips facets that need the administrator or have nothing to do', () => {
  const completeness = { facets: {
    PROFILE: { status: 'FAILED', can_retry: true, next_step: 'retry' },
    COMMENTS: { status: 'BLOCKED', can_retry: true, next_step: 'admin' },
    NEWS: { status: 'FAILED', can_retry: true, next_step: 'wait' },
    REVIEWS: { status: 'SUCCEEDED', can_retry: true, next_step: 'none' },
  } };
  assert.deepEqual(facetsWorthRetrying(completeness), ['PROFILE']);
});

test('comment filters and the action mark send the real requests', async (t) => {
  const seen = await serve(t, (_req, res) => res.end('{"comments":[],"next_offset":null}'));
  await competitorDataApi.comments('c1', { platform: 'YouTube', theme: 'price', action: 'open' });
  await competitorDataApi.setCommentAction('c1', 'r1', 'acted_on');
  await competitorDataApi.setCommentAction('c1', 'r1', null);
  assert.equal(seen[0].url, '/competitors/c1/reviews?sort=helpful&limit=20&offset=0&platform=YouTube&theme=price&action=open');
  assert.deepEqual([seen[1].method, seen[1].url, seen[1].body], ['PUT', '/competitors/c1/reviews/r1/action', { status: 'acted_on' }]);
  assert.deepEqual(seen[2].body, { status: null });
});
