import httpClient from '../../../shared/lib/httpClient.js';

// What we know about each competitor and why anything is missing: ratings, the
// real comments collected, people agreeing, sentiment, and data completeness with
// Retry (backend/src/ai/routers/competitor_enrichment.py), plus the market-price
// coverage of the company's own products.
export const competitorDataApi = {
  // One bulk read for every tracked competitor, keyed by competitor_id.
  overview: async () => (await httpClient.get('/competitor-data/overview')).data.competitors,

  // The real comments collected about one competitor. sort: 'helpful' | 'recent'.
  comments: async (id, { sort = 'helpful', limit = 20, offset = 0 } = {}) => {
    try {
      return (await httpClient.get(`/competitors/${encodeURIComponent(id)}/reviews`, { params: { sort, limit, offset } })).data;
    } catch (error) {
      if (error?.response?.status === 404) return null;
      throw error;
    }
  },

  dataStatus: async (id) => (await httpClient.get(`/competitors/${encodeURIComponent(id)}/data-status`)).data,

  // Retry one competitor now (waits for the result) or in the background.
  // facets: optional subset of PROFILE | SOCIAL_LINKS | REVIEWS | NEWS | COMMENTS.
  retry: async (id, { facets, background = false } = {}) => (await httpClient.post(
    `/competitors/${encodeURIComponent(id)}/enrich`,
    facets?.length ? { facets } : undefined,
    { params: background ? { background: true } : undefined },
  )).data,

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

export const FACET_ORDER = ['PROFILE', 'SOCIAL_LINKS', 'REVIEWS', 'NEWS', 'COMMENTS', 'PRICES', 'SOCIAL_CONTENT'];
// Facets the Retry button can re-collect; the others are fixed elsewhere (review a source, add a barcode).
export const RETRYABLE_FACETS = ['PROFILE', 'SOCIAL_LINKS', 'REVIEWS', 'NEWS', 'COMMENTS'];

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

// Merges the bulk overview onto discovery rows by competitor id (rows without data stay untouched).
export function withOverview(competitors, overview) {
  return (competitors || []).map((c) => ({ ...c, data: overview?.[c.competitor_id] || null }));
}
