import { useMutation, useQueryClient } from '@tanstack/react-query';
import { searchScopeApi } from '../api/searchScopeApi.js';

export function useUpdateSearchScope() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: searchScopeApi.updateSearchScope,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['search-scope'] });
      // The scope decides competitor relevance (src/ai/pricing/
      // competitor_classification.py) - existing overview/competitor
      // views must refetch to reflect it, not just this settings screen.
      queryClient.invalidateQueries({ queryKey: ['market-intelligence-overview'] });
      queryClient.invalidateQueries({ queryKey: ['competitors'] });
    },
  });
}
