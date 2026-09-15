import { useQuery } from '@tanstack/react-query';
import { inventoryApi } from '../api/inventoryApi.js';

export function useInventoryLevels() {
  return useQuery({
    queryKey: ['inventory-levels'],
    queryFn: inventoryApi.levels,
  });
}
