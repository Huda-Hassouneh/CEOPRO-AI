import { useQuery } from '@tanstack/react-query';

export function usePriceHistory() {
  return useQuery({
    queryKey: ['price-history'],
    queryFn: async () => ({ history: [] }),
  });
}
