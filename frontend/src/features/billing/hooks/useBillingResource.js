import { skipToken, useQuery, useQueryClient } from '@tanstack/react-query';
import { useAuthStore } from '../../auth/store/authStore.js';
// Preserve the original component query interface using KEEL's query authority.
export default function useBillingResource(key, fetcher) {
  const tenant = useAuthStore((state) => state.tenantId);
  const client = useQueryClient();
  const queryKey = ['original-billing', tenant, key];
  // skipToken, not just enabled:false: a disabled query with no queryFn still logs 'No queryFn' errors
  // whenever something refetches or invalidates it (seen 16x on the Billing page).
  const query = useQuery({ queryKey, queryFn: key && fetcher ? fetcher : skipToken, retry: false });
  const mutate = async (value, options = {}) => {
    if (value !== undefined) client.setQueryData(queryKey, value);
    if (options.revalidate !== false && key && fetcher) return query.refetch();
    return client.getQueryData(queryKey);
  };
  return { ...query, isLoading: Boolean(key) && query.isPending, mutate };
}
