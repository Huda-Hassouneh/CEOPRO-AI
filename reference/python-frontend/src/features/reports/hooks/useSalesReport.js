import { keepPreviousData, useQuery } from '@tanstack/react-query';
import { reportsApi } from '../api/reportsApi.js';

export function useSalesReport({ startDate, endDate, limit, offset } = {}) {
  return useQuery({
    queryKey: ['reports-sales', startDate, endDate, limit, offset],
    queryFn: () => reportsApi.getSalesReport({ startDate, endDate, limit, offset }),
    // Keep the current page on screen while the next one loads.
    placeholderData: keepPreviousData,
  });
}
