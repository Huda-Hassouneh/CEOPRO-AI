import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useAuthStore } from '../../auth/store/authStore.js';
// Preserve the original component query interface using KEEL's query authority.
export default function useBillingResource(key, fetcher) {
  const tenant = useAuthStore((state) => state.tenantId);
  const client = useQueryClient();
  const queryKey = ['original-billing', tenant, key];
  const query = useQuery({ queryKey, queryFn: fetcher, enabled: Boolean(key && fetcher), retry: false });
  const mutate = async (value, options = {}) => {
    if (value !== undefined) client.setQueryData(queryKey, value);
    if (options.revalidate !== false) return query.refetch();
    return client.getQueryData(queryKey);
  };
  return { ...query, isLoading: Boolean(key) && query.isPending, mutate };
}
