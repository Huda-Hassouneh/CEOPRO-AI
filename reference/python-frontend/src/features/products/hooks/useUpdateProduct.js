import { useMutation, useQueryClient } from '@tanstack/react-query';
import { productsApi } from '../api/productsApi.js';

export function useUpdateProduct() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: productsApi.update,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['products'] });
    },
  });
}
