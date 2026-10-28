import httpClient from '../../../shared/lib/httpClient.js';

// What we know about each competitor and why anything is missing: ratings, the
// real comments collected, people agreeing, sentiment, and data completeness with
// Retry (backend/src/ai/routers/competitor_enrichment.py), plus the market-price
// coverage of the company's own products.
export const competitorDataApi = {
  // One bulk read for every tracked competitor, keyed by competitor_id.
  overview: async () => (await httpClient.get('/competitor-data/overview')).data.competitors,

  // The real comments collected about one competitor. sort: 'helpful' | 'recent'; sentiment: 'positive' | 'negative' | 'neutral'.
  comments: async (id, { sort = 'helpful', limit = 20, offset = 0, sentiment, platform, theme, action } = {}) => {
    try {
      return (await httpClient.get(`/competitors/${encodeURIComponent(id)}/reviews`, { params: { sort, limit, offset, sentiment: sentiment || undefined, platform: platform || undefined, theme: theme || undefined, action: action || undefined } })).data;
    } catch (error) {
      if (error?.response?.status === 404) return null;
      throw error;
    }
  },

  // What was done about one comment: 'noted' | 'acted_on' | null (clears it).
  setCommentAction: async (competitorId, reviewId, status) => (await httpClient.put(
    `/competitors/${encodeURIComponent(competitorId)}/reviews/${encodeURIComponent(reviewId)}/action`, { status: status || null },
  )).data,

  dataStatus: async (id) => (await httpClient.get(`/competitors/${encodeURIComponent(id)}/data-status`)).data,

  // Retry one competitor now (waits for the result) or in the background.
  // facets: optional subset of PROFILE | SOCIAL_LINKS | REVIEWS | NEWS | COMMENTS | PRICES | SOCIAL_CONTENT | MARKET_MENUS.
  // depth 'deep' = "load more" (PRICES reads more pages and menu files, SOCIAL_CONTENT more posts); slow, so
  // pair it with background: true.
  retry: async (id, { facets, background = false, depth = 'standard' } = {}) => {
    const body = {};
    if (facets?.length) body.facets = facets;
    if (depth !== 'standard') body.depth = depth;
    return (await httpClient.post(
      `/competitors/${encodeURIComponent(id)}/enrich`,
      Object.keys(body).length ? body : undefined,
      { params: background ? { background: true } : undefined },
    )).data;
  },

  // "Retry all failed": queues one background job for every competitor facet that needs it.
  retryAllFailed: async () => (await httpClient.post('/competitors/enrich-failed')).data,

  // Which products have a market price, and why not for the rest.
  priceCoverage: async ({ includeCovered = false, missingBarcode = false, limit = 100, offset = 0 } = {}) => (await httpClient.get('/pricing/market-coverage', {
    params: { include_covered: includeCovered || undefined, missing_barcode: missingBarcode || undefined, limit, offset },
  })).data,

  // Looks up open-market prices for products that have none (queued; 202).
  findMissingPrices: async () => (await httpClient.post('/pricing/market-coverage/fill')).data,

  // Saves (or clears, with null) a product's barcode - the exact key for market prices.
  setBarcode: async (productId, barcode) => (await httpClient.patch(`/products/${encodeURIComponent(productId)}`, { barcode: barcode || null })).data,
};

export const THEMES = ['service', 'waiting', 'price', 'quality', 'cleanliness', 'staff', 'delivery', 'availability'];

export const FACET_ORDER = ['PROFILE', 'SOCIAL_LINKS', 'REVIEWS', 'NEWS', 'COMMENTS', 'PRICES', 'SOCIAL_CONTENT', 'MARKET_MENUS'];
// Facets the plain Retry button re-collects (free or already-budgeted sources); sent explicitly so the button keeps
// its behaviour as the server learns new facets.
export const RETRYABLE_FACETS = ['PROFILE', 'SOCIAL_LINKS', 'REVIEWS', 'NEWS', 'COMMENTS'];
// Facets with their own button, always run in the background: PRICES re-reads the competitor's website and its
// menu files (OCR), SOCIAL_CONTENT reads social posts through a paid provider, MARKET_MENUS reads the competitor's
// delivery-app listings and menu photos on Google Maps and the web (searches, photo calls and OCR).
export const ON_REQUEST_FACETS = ['PRICES', 'SOCIAL_CONTENT', 'MARKET_MENUS'];

// What an on-request facet's buttons should offer right now: whether it can run at all, and whether
// "load more" makes sense (something was already collected that a deeper read can extend).
export function onRequestAction(completeness, name) {
  const facet = completeness?.facets?.[name];
  if (!ON_REQUEST_FACETS.includes(name) || !facet?.can_retry) return null;
  const hasData = facet.status === 'SUCCEEDED' || facet.status === 'PARTIAL';
  return { canRun: true, canLoadMore: hasData, hasData };
}

export function facetTone(status) {
  switch (status) {
    case 'SUCCEEDED': return 'success';
    case 'PARTIAL': return 'accent';
    case 'FAILED': return 'danger';
    case 'BLOCKED': return 'warning';
    default: return 'neutral'; // PENDING, NOT_APPLICABLE
  }
}

export function completenessTone(score) {
  if (score == null) return 'neutral';
  if (score >= 75) return 'success';
  if (score >= 40) return 'accent';
  return 'warning';
}

// Facets that can be retried right now and are not already fully collected.
export function retryableFacets(completeness) {
  if (!completeness?.facets) return [];
  return RETRYABLE_FACETS.filter((name) => {
    const facet = completeness.facets[name];
    return facet?.can_retry && facet.status !== 'SUCCEEDED';
  });
}

// Facets a plain Retry should run: those where trying again can help (not a missing key, not "nothing to do").
export function facetsWorthRetrying(completeness) {
  return retryableFacets(completeness).filter((name) => facetNextStep(completeness.facets[name]) === 'retry');
}

// A gap the owner can fix with a click somewhere else (review a source's terms).
export function facetActions(completeness) {
  if (!completeness?.facets) return [];
  return FACET_ORDER
    .map((name) => ({ name, facet: completeness.facets[name] }))
    .filter(({ facet }) => facet?.action)
    .map(({ name, facet }) => ({ name, action: facet.action, sourceIds: facet.action_source_ids || [] }));
}

// Translation key for why a facet is empty; unknown codes fall back to a generic one.
export function reasonKey(code, known = REASON_CODES) {
  return known.includes(code) ? `competitorData.reason.${code}` : 'competitorData.reason.UNKNOWN';
}

export const REASON_CODES = [
  'NO_CREDENTIALS', 'CREDENTIALS_REJECTED', 'QUOTA_EXHAUSTED', 'PROVIDER_ERROR', 'NO_MATCH', 'INCOMPLETE_LISTING',
  'NO_WEBSITE', 'ROBOTS_DISALLOWED', 'SITE_UNREACHABLE', 'SHARED_RECORD', 'NO_PRODUCTS_MAPPED', 'TERMS_UNREVIEWED',
  'NO_DATA_COLLECTED', 'COLLECTOR_NOT_ENABLED', 'NO_SOCIAL_LINKS', 'NO_PLACE_ID', 'PLATFORM_APPROVAL_MISSING',
  'SERVICE_MISCONFIGURED', 'NOT_ATTEMPTED', 'NO_FEED', 'NO_NEWS', 'NO_VIDEOS',
  'NO_PRICES_PUBLISHED', 'JS_RENDERED', 'OCR_NOT_AVAILABLE', 'NOT_OWN_SITE', 'NO_POSTS',
];

export const PRICE_REASON_CODES = ['NO_COMPETITOR_MAPPED', 'TERMS_UNREVIEWED', 'ROBOTS_DISALLOWED', 'NO_DATA_COLLECTED'];

// How a retry request ended, in one word for the UI.
export function retryOutcome(response) {
  const results = Object.values(response?.results || {});
  if (response?.queued !== undefined) return response.already_queued ? 'alreadyQueued' : 'queued';
  if (results.length && results.every((r) => r.status === 'SUCCEEDED')) return 'succeeded';
  if (results.some((r) => r.status === 'SUCCEEDED' || r.status === 'PARTIAL')) return 'partial';
  return 'failed';
}

// Who has to act for a facet to fill, as the server reports it (`next_step`): 'retry' (trying again may help),
// 'wait' (retried automatically), 'owner' (a click elsewhere), 'admin' (service setup), 'none' (nothing to do).
export const NEXT_STEPS = ['none', 'retry', 'wait', 'owner', 'admin'];

export function nextStepKey(step) {
  return `competitorData.nextStep.${NEXT_STEPS.includes(step) ? step : 'retry'}`;
}

// A facet's next step; servers that predate the field fall back to "retry" when Retry is possible.
export function facetNextStep(facet) {
  if (!facet) return 'none';
  if (NEXT_STEPS.includes(facet.next_step)) return facet.next_step;
  if (facet.status === 'SUCCEEDED' || facet.status === 'NOT_APPLICABLE') return 'none';
  return facet.can_retry ? 'retry' : 'none';
}

// Facets that are not collected, with why: the list shown under a competitor and after a Retry.
export function facetGaps(completeness) {
  if (!completeness?.facets) return [];
  return FACET_ORDER
    .map((name) => ({ name, facet: completeness.facets[name] }))
    .filter(({ facet }) => facet && facet.status !== 'SUCCEEDED' && facet.status !== 'NOT_APPLICABLE')
    .map(({ name, facet }) => ({
      name, status: facet.status, reasonCode: facet.reason_code, detail: facet.reason_detail || null, nextStep: facetNextStep(facet),
    }));
}

// What a Retry answered, facet by facet: the reason and detail for each one that did not fully succeed.
export function retryFindings(response) {
  return Object.entries(response?.results || {})
    .filter(([, r]) => r && r.status !== 'SUCCEEDED' && r.status !== 'THROTTLED')
    .map(([name, r]) => ({
      name, status: r.status, reasonCode: r.reason_code, detail: r.reason_detail || null, nextStep: facetNextStep(r),
    }));
}

// Merges the bulk overview onto discovery rows by competitor id (rows without data stay untouched).
export function withOverview(competitors, overview) {
  return (competitors || []).map((c) => ({ ...c, data: overview?.[c.competitor_id] || null }));
}

// ---- Prices read from a website, menu or social post: where each came from, and the owner's check of it ----

// Roles the backend lets verify a price (POST /discovery/competitors/{id}/intel/review is owner/admin only).
export const PRICE_REVIEW_ROLES = ['owner', 'admin'];

export function canReviewPrices(roles) {
  const have = (roles || []).map((role) => String(role).trim().toLowerCase());
  return PRICE_REVIEW_ROLES.some((role) => have.includes(role));
}

// How a price fact was read, as a translation suffix: page text (default), a PDF's text, picture OCR, a vision
// model, or a social post caption.
export function intelOrigin(fact) {
  const by = fact?.extracted_by;
  return ['pdf_text', 'ocr', 'vision', 'caption'].includes(by) ? by : 'page';
}

// A read that is not the site's own structured data is worth a second look: only these show "check this". So is a
// delivery-app listing whose page only partly names the competitor (it may be another branch or business).
export function needsCheck(fact) {
  if (fact?.verified) return false;
  return ['ocr', 'vision', 'caption'].includes(intelOrigin(fact)) || (fact?.channel === 'delivery' && !fact?.listing_verified);
}

// Where a fact came from outside the website, if anywhere: 'instagram' | 'facebook' (posts), 'delivery' (a delivery
// or menu app listing), 'maps_photos' (Google Maps photos) or 'web_photos' (a menu picture found on the web).
export function intelChannel(fact) {
  return fact?.channel && fact.channel !== 'website' ? fact.channel : null;
}

// Validates the owner's correction before it is sent; returns the number or null.
export function parseCorrectedPrice(text) {
  const normalised = String(text ?? '').trim().replace(/[٠-٩]/g, (d) => String('٠١٢٣٤٥٦٧٨٩'.indexOf(d))).replace(',', '.');
  if (!/^\d+(\.\d{1,4})?$/.test(normalised)) return null;
  const value = Number(normalised);
  return Number.isFinite(value) ? value : null;
}
