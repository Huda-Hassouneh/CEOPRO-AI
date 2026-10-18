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
