import { useQuery } from '@tanstack/react-query';
import { dashboardApi } from '../api/dashboardApi.js';

export function useDashboardAggregate(periodDays = 30, companyId = null) {
  return useQuery({
    queryKey: ['dashboard-aggregate', companyId, periodDays],
    queryFn: () => dashboardApi.getAggregate({ periodDays, companyId }),
  });
}
