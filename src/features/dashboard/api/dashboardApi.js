import { getMockDashboard } from '../mocks/dashboardMockData.js';

export const dashboardApi = {
  // Replace this mock adapter with GET /companies/:companyId/dashboard.
  // The page already consumes the backend-ready response shape returned here.
  getAggregate: async ({ periodDays = 30 } = {}) => getMockDashboard(periodDays),
};
