import { useMutation, useQueryClient } from '@tanstack/react-query';
import { quickSaleApi } from '../api/quickSaleApi.js';

export function useQuickSale() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: quickSaleApi.sale,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['products'] });
      // A quick sale writes a real invoices/invoice_items row - the same
      // table GET /reports/sales reads - so the Sales/POS page's recent
      // sales list and today's summary (and the Reports page's own sales
      // table) must refresh too, not just the product stock count.
      queryClient.invalidateQueries({ queryKey: ['reports-sales'] });
      // ...and everything built on sales: the product page, demand, the
      // command center.
      queryClient.invalidateQueries({ queryKey: ['product-intelligence'] });
      queryClient.invalidateQueries({ queryKey: ['demand-overview'] });
      queryClient.invalidateQueries({ queryKey: ['dashboard'] });
    },
  });
}
