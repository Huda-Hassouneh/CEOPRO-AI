import { useQuery } from '@tanstack/react-query';
import { productsApi } from '../api/productsApi.js';

export function useProducts() {
  return useQuery({
    queryKey: ['products'],
    queryFn: productsApi.list,
  });
}
