import {useAuthStore} from '../../auth/store/authStore.js';
import httpClient from '../../../shared/lib/httpClient.js';

// The real backend endpoint - backend/src/ai/routers/pricing.py's
// POST /pricing/recommend?product_id=... (product_id is a query param,
// not a JSON body, matching that endpoint's own real signature). Runs
// the real pricing/pipeline.py::run_price_recommendation() - a rule-based
// comparison against real scraped competitor prices, with a real price-
// change guardrail and a real minimum-margin-over-cost guardrail - never
// a fabricated number when there's nothing to compare against (status
// "UNKNOWN" when no competitor price data exists for this product yet).
const pendingRequests=new Map();
export const pricingApi = {
  recommend: async (productId) => {
    const tenant=useAuthStore.getState().tenantId,key=`keel.pricing.${tenant}.${productId}`;
    let requestKey=pendingRequests.get(key);
    try{requestKey=globalThis.sessionStorage?.getItem(key)||requestKey;}catch{ /* in-memory retry identity remains */ }
    requestKey ||= crypto.randomUUID();pendingRequests.set(key,requestKey);
    try{globalThis.sessionStorage?.setItem(key,requestKey);}catch{ /* storage may be disabled */ }
    const response = await httpClient.post('/pricing/recommend', null, { params: { product_id: productId },headers:{'Idempotency-Key':requestKey} });
    pendingRequests.delete(key);try{globalThis.sessionStorage?.removeItem(key);}catch{ /* acknowledged */ }
    return response.data;
  },

  // Read-only history from the shared evidence/recommendation tables.
  recommendationHistory: async (productId, { limit = 20, offset = 0 } = {}) => (
    await httpClient.get(`/pricing/history/${encodeURIComponent(productId)}`, { params: { limit, offset } })
  ).data,

  // backend/src/ai/routers/pricing.py - the price comparison ladder: how a product relates to what competitors
  // sell, in four tiers (EXACT / EQUIVALENT / SIMILAR / ADDED_VALUE). Reads only; stored competitor items are
  // classified by the market scraper's code path (market_scraper/price_comparison/).
  // Per product: counts per tier and the headline (your price against the middle of the best tier). At most 100 ids.
  comparisons: async (productIds) => (await httpClient.get('/pricing/comparisons', { params: { product_ids: productIds.join(',') } })).data.products,

  // One product's full ladder: every tier with its competitor items, comparable prices and reasons.
  ladder: async (productId) => (await httpClient.get(`/pricing/comparisons/${encodeURIComponent(productId)}`)).data,

  // The owner's correction of one comparison (owner/admin only): verdict 'ADDITION' | 'VARIANT' | 'NOT_COMPARABLE', or null
  // to clear it. Kept by item name, so it survives re-reads; returns the product's recomputed ladder.
  setComparisonOverride: async (productId, { competitorId, itemName, verdict }) => (await httpClient.put(
    `/pricing/comparisons/${encodeURIComponent(productId)}/override`,
    { competitor_id: competitorId, item_name: itemName, verdict: verdict ?? null },
  )).data,

  // Recomputes the ladder from the competitor items already stored (no crawl, no credits).
  refreshComparisons: async () => (await httpClient.post('/pricing/comparisons/refresh')).data,

  // Added-value premium bands per category; setPremiumBand is owner/admin only (bandPct null clears the owner's setting).
  premiumBands: async () => (await httpClient.get('/pricing/premium-bands')).data,
  setPremiumBand: async ({ category, bandPct }) => (await httpClient.put('/pricing/premium-bands', { category: category ?? null, band_pct: bandPct ?? null })).data,

  // GET /reports/price-comparison: every product with competitor evidence and its ladder.
  comparisonReport: async (limit = 50) => (await httpClient.get('/reports/price-comparison', { params: { limit } })).data,
};
