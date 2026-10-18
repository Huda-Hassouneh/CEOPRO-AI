import { useCatalogProduct } from './useCatalog.js';
export function useInventoryLevels(id) { const query = useCatalogProduct(id); return { ...query, data: query.data?.inventory }; }
