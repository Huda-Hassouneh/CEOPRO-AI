import httpClient from '../../../shared/lib/httpClient.js';

// The real backend endpoint - backend/src/ai/routers/sales.py's
// POST /sales/quick-sale, which writes one real invoices+invoice_items row.
export const quickSaleApi = {
  sale: async ({ productId, quantity, unitPrice } = {}) => {
    const response = await httpClient.post('/sales/quick-sale', {
      product_id: productId,
      quantity,
      ...(unitPrice != null ? { unit_price: unitPrice } : {}),
    });
    return { ok: true, sale: response.data };
  },
};
