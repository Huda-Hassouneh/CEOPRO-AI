import { useMutation } from '@tanstack/react-query';
import { quickSaleApi } from '../api/quickSaleApi.js';

export function useQuickSale() {
  return useMutation({
    mutationFn: quickSaleApi.sale,
  });
}
