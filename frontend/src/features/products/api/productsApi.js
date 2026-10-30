import httpClient from '../../../shared/lib/httpClient.js';

// The real backend endpoints - backend/src/ai/routers/products.py's
// GET/POST /products, GET/PATCH/DELETE /products/{id}. product_name/brand/
// category/description are JSONB {locale: text} dicts server-side;
// list rows arrive pre-resolved to one display string (COALESCE'd
// server-side), while get/create/update exchange the full dict so an
// edit form can offer every locale.

export const productsApi = {
  list: async ({ limit, offset, search } = {}) => {
    const response = await httpClient.get('/products', { params: { limit, offset, search } });
    return response.data;
  },

  getById: async (id) => {
    const response = await httpClient.get(`/products/${encodeURIComponent(id)}`);
    return { id, product: response.data };
  },

  create: async (payload) => {
    const response = await httpClient.post('/products', payload);
    return { ok: true, product: response.data };
  },

  update: async ({ id, ...payload }) => {
    const response = await httpClient.patch(`/products/${encodeURIComponent(id)}`, payload);
    return { ok: true, product: response.data };
  },

  // Manual canonical stock entry. Provider inventory observations remain
  // source-owned evidence and are never written through this operation.
  updateInventory: async ({ id, stock_quantity, reorder_level, safety_stock }) => {
    const response = await httpClient.patch(`/products/${encodeURIComponent(id)}/inventory`, {
      stock_quantity, reorder_level, safety_stock,
    });
    return response.data;
  },

  // Soft-delete server-side (products.py::delete_product) - the row stops
  // appearing in list/getById immediately, never a real DELETE FROM.
  remove: async (id) => {
    await httpClient.delete(`/products/${encodeURIComponent(id)}`);
    return { ok: true, id };
  },
};
