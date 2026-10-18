import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { demandApi } from '../api/demandApi.js';

const isRefreshing = (data) => data?.refresh?.state === 'running';

export function useDemandOverview({ productId } = {}) {
  return useQuery({
    queryKey: ['demand-overview', productId || 'all'],
    queryFn: () => demandApi.overview({ productId }),
    // While forecasts are being recalculated, reload every 2.5 s so the page
    // fills in as soon as they're ready.
    refetchInterval: (query) => (isRefreshing(query.state.data) ? 2500 : false),
  });
}

export function useRefreshForecasts() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => demandApi.refresh({ allProducts: true }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['demand-overview'] }),
  });
}
