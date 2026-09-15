import { useQuery } from '@tanstack/react-query';
import { forecastingApi } from '../api/forecastingApi.js';

export function useForecastDetail(id) {
  return useQuery({
    queryKey: ['forecast-detail', id],
    queryFn: () => forecastingApi.getForecastDetail(id),
    enabled: Boolean(id),
  });
}
