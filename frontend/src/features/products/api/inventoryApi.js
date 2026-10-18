import { productsApi } from './productsApi.js';
export const inventoryApi = { levels: async (id, options) => (await productsApi.getById(id, options)).inventory };
