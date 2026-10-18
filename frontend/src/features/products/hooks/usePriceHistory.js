import { useCatalogProduct } from './useCatalog.js';
export function usePriceHistory(id) { const query = useCatalogProduct(id); return { ...query, data: query.data ? { history: query.data.priceHistory } : undefined }; }
