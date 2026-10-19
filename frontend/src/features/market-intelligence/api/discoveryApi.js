import httpClient from '../../../shared/lib/httpClient.js';

// Competitor discovery (backend/src/ai/routers/discovery.py): what the scan
// looks for, running it, and the competitors it found with their sources.
export const discoveryApi = {
  status: async () => (await httpClient.get('/discovery/status')).data,
  industries: async () => (await httpClient.get('/discovery/industries')).data.industries,
  start: async ({ radiusKm } = {}) => (await httpClient.post('/discovery/runs', radiusKm ? { radius_km: radiusKm } : {})).data,
  run: async (runId) => (await httpClient.get(`/discovery/runs/${encodeURIComponent(runId)}`)).data,
  competitors: async ({ status = 'all', sort = 'relevance', q, origin, relationship, limit = 100, offset = 0 } = {}) => (await httpClient.get('/discovery/competitors', {
    params: { status, sort, q: q || undefined, origin: origin || undefined, relationship: relationship || undefined, limit, offset },
  })).data,
  competitor: async (id) => {
    try {
      return (await httpClient.get(`/discovery/competitors/${encodeURIComponent(id)}`)).data;
    } catch (error) {
      if (error?.response?.status === 404) return null;
      throw error;
    }
  },
  track: async (id) => (await httpClient.post(`/discovery/competitors/${encodeURIComponent(id)}/track`)).data,
  untrack: async (id) => (await httpClient.delete(`/discovery/competitors/${encodeURIComponent(id)}/track`)).data,
  // Reads the competitor's website again now (also the retry after a failed read).
  refresh: async (id) => (await httpClient.post(`/discovery/competitors/${encodeURIComponent(id)}/refresh`)).data,
  // The owner's check of one price read from the site, a menu or a post (owner/admin only).
  // verdict: CONFIRMED | CORRECTED (with correctedPrice) | REJECTED | CLEARED (withdraws an earlier decision).
  reviewIntel: async (competitorId, { intelId, verdict, correctedPrice, currency, note }) => (await httpClient.post(
    `/discovery/competitors/${encodeURIComponent(competitorId)}/intel/review`,
    { intel_id: intelId, verdict, corrected_price: correctedPrice, currency, note },
  )).data,
  // Price changes on a competitor's own menu / site / posts (newest first). includeUnreliable adds changes between two
  // weak reads (picture, caption or AI reads), which the server leaves out by default.
  priceChanges: async (competitorId, { days = 90, includeUnreliable = false, limit = 50 } = {}) => (await httpClient.get(
    `/discovery/competitors/${encodeURIComponent(competitorId)}/price-changes`,
    { params: { days, include_unreliable: includeUnreliable || undefined, limit } },
  )).data.changes,
  recentPriceChanges: async ({ days = 30, includeUnreliable = false, limit = 30 } = {}) => (await httpClient.get('/discovery/price-changes', {
    params: { days, include_unreliable: includeUnreliable || undefined, limit },
  })).data.changes,
  // Which of the competitor's items is matched to which of your products, the priced items you can choose from, and rejections.
  matches: async (competitorId) => (await httpClient.get(`/discovery/competitors/${encodeURIComponent(competitorId)}/matches`)).data,
  // "This item is not that product" / "this item is that product" / back to automatic (owner/admin only).
  rejectMatch: async (competitorId, productId) => (await httpClient.post(
    `/discovery/competitors/${encodeURIComponent(competitorId)}/matches/reject`, { product_id: productId })).data,
  chooseMatch: async (competitorId, { productId, intelId }) => (await httpClient.post(
    `/discovery/competitors/${encodeURIComponent(competitorId)}/matches`, { product_id: productId, intel_id: intelId })).data,
  clearMatch: async (competitorId, productId) => (await httpClient.delete(
    `/discovery/competitors/${encodeURIComponent(competitorId)}/matches/${encodeURIComponent(productId)}`)).data,
  // AI analysis built only on collected facts; every point cites them.
  analyse: async (id) => (await httpClient.post(`/discovery/competitors/${encodeURIComponent(id)}/analysis`)).data,
  news: async ({ competitorId, limit = 30 } = {}) => (await httpClient.get('/discovery/news', {
    params: { competitor_id: competitorId || undefined, limit },
  })).data.articles,
  // Counts and price ranges over the stored competitors (no AI).
  marketStructure: async () => (await httpClient.get('/discovery/market/structure')).data,
  marketAnalysis: async () => (await httpClient.get('/discovery/market/analysis')).data.analysis,
  refreshMarketAnalysis: async () => (await httpClient.post('/discovery/market/analysis')).data.analysis,
};

export const RUN_ACTIVE = ['queued', 'running'];
