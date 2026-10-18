import { useMutation, useQueryClient } from '@tanstack/react-query';
import { productsApi } from '../api/productsApi.js';

export function useDeleteProduct() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: productsApi.remove,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['products'] });
    },
  });
}
