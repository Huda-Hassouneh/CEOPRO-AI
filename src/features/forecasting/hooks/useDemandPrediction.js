import { useQuery } from '@tanstack/react-query';
import { forecastingApi } from '../api/forecastingApi.js';

export function useDemandPrediction({ companyId, productId, periodDays } = {}) {
  return useQuery({
    queryKey: ['demand-prediction', companyId, productId, periodDays],
    queryFn: () => forecastingApi.predictDemand({ companyId, productId, periodDays }),
  });
}
