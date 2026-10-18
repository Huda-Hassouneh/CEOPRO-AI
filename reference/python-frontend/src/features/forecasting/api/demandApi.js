import httpClient from '../../../shared/lib/httpClient.js';

// GET /forecasting/overview (backend/src/ai/forecasting/overview.py): the
// company's real sales, stock and 30-day forecasts in one response. The
// backend starts a background forecast refresh when any product's forecast
// is missing or older than its latest sale; `refresh` reports its progress.
export const demandApi = {
  overview: async ({ productId } = {}) => {
    const response = await httpClient.get('/forecasting/overview', {
      params: { product_id: productId && productId !== 'all' ? productId : undefined },
    });
    return response.data;
  },
  refresh: async ({ allProducts = true } = {}) => {
    const response = await httpClient.post('/forecasting/refresh', null, { params: { all_products: allProducts } });
    return response.data;
  },
};
