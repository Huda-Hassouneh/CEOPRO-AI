import { useQuery } from '@tanstack/react-query';
import { forecastingApi } from '../api/forecastingApi.js';

export function useModelAccuracy() {
  return useQuery({
    queryKey: ['model-accuracy'],
    queryFn: forecastingApi.getModelAccuracy,
  });
}
