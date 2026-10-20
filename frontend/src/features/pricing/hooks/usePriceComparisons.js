import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { pricingApi } from '../api/pricingApi.js';

const KEY = ['pricing', 'comparisons'];

// Per-product tier counts + headline for a page of products.
export function usePriceComparisonSummary(productIds) {
  const ids = [...productIds].sort();
  return useQuery({
    queryKey: [...KEY, 'summary', ids.join(',')],
    queryFn: () => pricingApi.comparisons(ids),
    enabled: ids.length > 0,
    staleTime: 60_000,
    placeholderData: keepPreviousData,
  });
}

// One product's full ladder.
export function usePriceLadder(productId, enabled = true) {
  return useQuery({
    queryKey: [...KEY, 'ladder', productId],
    queryFn: () => pricingApi.ladder(productId),
    enabled: Boolean(productId) && enabled,
    staleTime: 60_000,
  });
}

export function useRefreshComparisons() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: pricingApi.refreshComparisons,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: KEY }),
  });
}

// The owner's decision on one comparison; the response is the product's new ladder.
export function useComparisonOverride(productId) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (decision) => pricingApi.setComparisonOverride(productId, decision),
    onSuccess: (ladder) => {
      queryClient.setQueryData([...KEY, 'ladder', productId], ladder);
      queryClient.invalidateQueries({ queryKey: [...KEY, 'summary'] });
      queryClient.invalidateQueries({ queryKey: ['product-intelligence', productId] });
    },
  });
}

// Sets (or clears, with bandPct null) the owner's premium band for a category; every ladder is re-read afterwards.
export function useSetPremiumBand() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: pricingApi.setPremiumBand,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: KEY }),
  });
}

// The report: every product that has competitor evidence, with its ladder.
export function usePriceComparisonReport(limit = 50) {
  return useQuery({ queryKey: [...KEY, 'report', limit], queryFn: () => pricingApi.comparisonReport(limit), staleTime: 60_000 });
}
