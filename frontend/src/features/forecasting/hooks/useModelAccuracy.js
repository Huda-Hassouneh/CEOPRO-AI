import { useDemandPrediction } from './useDemandPrediction.js';
export function useModelAccuracy(periodDays = 30) {
  const query = useDemandPrediction({ productId: 'all', periodDays });
  return { ...query, data: query.data ? {
    models: query.data.modelEvaluations ?? [], filters: query.data.filters,
    featureAccess: query.data.featureAccess
  } : null };
}
