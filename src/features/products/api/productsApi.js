export const productsApi = {
  list: async () => ({ products: [] }),
  getById: async (id) => ({ id, product: null }),
  create: async (payload) => ({ ok: true, payload }),
  update: async (payload) => ({ ok: true, payload }),
};
