import { useQuery } from '@tanstack/react-query';
import { productsApi } from '../api/productsApi.js';

export function useProduct(id) {
  return useQuery({
    queryKey: ['product', id],
    queryFn: () => productsApi.getById(id),
    enabled: Boolean(id),
  });
}
