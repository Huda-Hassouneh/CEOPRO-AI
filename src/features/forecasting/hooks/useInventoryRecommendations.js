import { useQuery } from '@tanstack/react-query';
import { forecastingApi } from '../api/forecastingApi.js';

export function useInventoryRecommendations() {
  return useQuery({
    queryKey: ['inventory-recommendations'],
    queryFn: forecastingApi.getRecommendations,
  });
}
