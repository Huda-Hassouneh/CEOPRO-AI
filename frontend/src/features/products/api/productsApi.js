import httpClient from '../../../shared/lib/httpClient.js';
const unwrap = (response) => response.data?.data ?? response.data;
export const productsApi = {
  previewGtins: async (file) => {const body=new FormData();body.append('file',file);return unwrap(await httpClient.post('/products/gtin-import/preview',body));},
  applyGtins: async (payload) => unwrap(await httpClient.post('/products/gtin-import/apply',payload)),
  list: async ({ signal, ...params } = {}) => unwrap(await httpClient.get('/products', { params, signal })),
  getById: async (id, { signal } = {}) => unwrap(await httpClient.get(`/products/${encodeURIComponent(id)}`, { signal })),
  create: async (payload) => unwrap(await httpClient.post('/products', payload)),
  update: async ({ id, ...payload }) => unwrap(await httpClient.patch(`/products/${encodeURIComponent(id)}`, payload)),
  archive: async ({ id, expectedVersion }) => unwrap(await httpClient.delete(`/products/${encodeURIComponent(id)}`, { data: { expectedVersion } })),
  restore: async ({ id, expectedVersion }) => unwrap(await httpClient.post(`/products/${encodeURIComponent(id)}/restore`, { expectedVersion }))
};
