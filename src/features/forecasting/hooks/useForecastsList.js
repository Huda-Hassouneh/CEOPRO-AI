import { useQuery } from '@tanstack/react-query';
import { forecastingApi } from '../api/forecastingApi.js';

export function useForecastsList() {
  return useQuery({
    queryKey: ['forecasts-list'],
    queryFn: forecastingApi.listForecasts,
  });
}
