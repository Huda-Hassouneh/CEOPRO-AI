import { getMockDemandDetail, getMockDemandOverview } from '../mocks/demandPredictionMockData.js';

export const forecastingApi = {
  listForecasts: async () => ({ forecasts: [] }),
  // Future: GET /companies/:companyId/demand-forecast/:productId
  getForecastDetail: async (id) => getMockDemandDetail(id),
  // Future: GET /companies/:companyId/demand-forecast?productId=&periodDays=
  predictDemand: async (params) => getMockDemandOverview(params),
  getRecommendations: async () => ({ recommendations: [] }),
  getModelAccuracy: async () => ({ accuracy: {} }),
  // No backend export endpoint currently exists.
  requestTablePdf: async () => ({ available: false }),
};
