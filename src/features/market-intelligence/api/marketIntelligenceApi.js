import { getMockMarketIntelligence } from '../mocks/marketIntelligenceMockData.js';

export const marketIntelligenceApi = {
  // Future: GET /companies/:companyId/market-intelligence?productId=&periodDays=
  getOverview: async (params) => getMockMarketIntelligence(params),
  // Future: POST /companies/:companyId/market-intelligence/exports
  requestPdfExport: async () => ({ available: false }),
};
