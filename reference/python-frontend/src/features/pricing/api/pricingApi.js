import httpClient from '../../../shared/lib/httpClient.js';

// The real backend endpoint - backend/src/ai/routers/pricing.py's
// POST /pricing/recommend?product_id=... (product_id is a query param,
// not a JSON body, matching that endpoint's own real signature). Runs
// the real pricing/pipeline.py::run_price_recommendation() - a rule-based
// comparison against real scraped competitor prices, with a real price-
// change guardrail and a real minimum-margin-over-cost guardrail - never
// a fabricated number when there's nothing to compare against (status
// "UNKNOWN" when no competitor price data exists for this product yet).
export const pricingApi = {
  recommend: async (productId) => {
    const response = await httpClient.post('/pricing/recommend', null, { params: { product_id: productId } });
    return response.data;
  },
};
