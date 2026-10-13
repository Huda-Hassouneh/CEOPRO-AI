import httpClient from '../../../shared/lib/httpClient.js';

// The real backend endpoints - backend/src/ai/routers/reports.py, backed
// by real invoice/product data (dashboard/reports.py,
// dashboard/financial_summary.py). No mock/fixture data anywhere in this
// module - an `available: false` result means the real request failed
// (network/auth/server error), never a fabricated stand-in for it.

export const reportsApi = Object.freeze({
  getSalesReport: async ({ startDate, endDate, limit, offset } = {}) => {
    try {
      const response = await httpClient.get('/reports/sales', {
        params: {
          start_date: startDate || undefined,
          end_date: endDate || undefined,
          limit: limit || undefined,
          offset: offset || undefined,
        },
      });
      return { available: true, ...response.data };
    } catch {
      return { available: false, rows: [], returned_row_count: 0, total_row_count: 0, truncated: false };
    }
  },

  // The whole period, streamed by the server - not just the rows the page
  // has loaded. Returns the file as a Blob to save, or null on failure.
  exportSales: async ({ format, lang, startDate, endDate } = {}) => {
    try {
      const response = await httpClient.get('/reports/sales/export', {
        params: {
          format,
          lang: lang === 'ar' ? 'ar' : 'en',
          start_date: startDate || undefined,
          end_date: endDate || undefined,
        },
        responseType: 'blob',
        timeout: 300000,
      });
      return response.data;
    } catch {
      return null;
    }
  },

  getFinancialSummary: async ({ windowDays } = {}) => {
    try {
      const response = await httpClient.get('/reports/financial-summary', {
        params: { window_days: windowDays || undefined },
      });
      return { available: true, ...response.data };
    } catch {
      return { available: false };
    }
  },
});
