import { useMutation, useQueryClient } from '@tanstack/react-query';
import { companyApi } from '../api/companyApi.js';

export function useUpdateTargetMarkets() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: companyApi.updateTargetMarkets,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['settings-target-markets'] });
      // A declared target market feeds real competitor discovery/
      // classification (competitor_classification.py::
      // _in_target_market_scope(), sector_detection.py::
      // resolve_tenant_geo_scope()) - existing Market Intelligence views
      // must refetch to reflect it, same as useUpdateSearchScope.js.
      queryClient.invalidateQueries({ queryKey: ['market-intelligence-overview'] });
      queryClient.invalidateQueries({ queryKey: ['competitors'] });
    },
  });
}
