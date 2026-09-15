import { useMutation } from '@tanstack/react-query';
import { productsApi } from '../api/productsApi.js';

export function useCreateProduct() {
  return useMutation({
    mutationFn: productsApi.create,
  });
}
