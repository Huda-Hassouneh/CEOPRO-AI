import { useQuery } from '@tanstack/react-query';

// Small SWR-shaped adapter for the original billing components. Queries remain
// owned by the app's existing TanStack Query client.
export default function useSWRCompat(key, fetcher, options = {}) {
  const enabled = key != null && typeof fetcher === 'function';
  const queryKey = Array.isArray(key) ? key : [key];
  const query = useQuery({
    queryKey,
    queryFn: fetcher,
    enabled,
    retry: options.shouldRetryOnError ?? false,
    refetchOnWindowFocus: options.revalidateOnFocus ?? false,
  });
  return {
    data: query.data,
    error: query.error,
    isLoading: query.isLoading,
    isValidating: query.isFetching,
    mutate: async () => (await query.refetch()).data,
  };
}