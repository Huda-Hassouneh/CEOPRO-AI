import { useQuery } from '@tanstack/react-query';
import { reportsApi } from '../api/reportsApi.js';

export function useFinancialSummaryReport({ windowDays } = {}) {
  return useQuery({
    queryKey: ['reports-financial-summary', windowDays],
    queryFn: () => reportsApi.getFinancialSummary({ windowDays }),
  });
}
