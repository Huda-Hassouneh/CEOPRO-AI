import { translateCurrent } from '../../../shared/lib/i18n.js';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useAuthStore } from '../../auth/store/authStore.js';
import { productsApi } from '../api/productsApi.js';
export function useCatalog(options = {}) {
  const tenant = useAuthStore((state) => state.tenantId);
  return useQuery({ queryKey: ['product-catalog', tenant, options], queryFn: ({ signal }) => productsApi.list({ ...options, signal }), enabled: Boolean(tenant), placeholderData: undefined });
}
export function useCatalogProduct(id) {
  const tenant = useAuthStore((state) => state.tenantId);
  return useQuery({ queryKey: ['catalog-product', tenant, id], queryFn: ({ signal }) => productsApi.getById(id, { signal }), enabled: Boolean(tenant && id), placeholderData: undefined });
}
export function useCatalogMutation(action) {
  const client = useQueryClient(); const tenant = useAuthStore((state) => state.tenantId);
  return useMutation({ mutationKey: ['catalog-write', tenant, action],
    mutationFn: (input) => {
      if (useAuthStore.getState().tenantId !== tenant) throw new Error(translateCurrent("interfaceCopy.sessionChangedReloadThisPage"));
      return productsApi[action](input);
    },
    onSuccess: async () => {
      if (useAuthStore.getState().tenantId !== tenant) return;
      for (const key of ['product-catalog', 'catalog-product', 'dashboard-aggregate', 'demand-prediction', 'forecast-detail', 'market-intelligence-overview', 'subscription'])
        await client.invalidateQueries({ predicate: (query) => query.queryKey[0] === key && (query.queryKey[1] === tenant || key === 'market-intelligence-overview' || key === 'subscription') });
    }
  });
}
