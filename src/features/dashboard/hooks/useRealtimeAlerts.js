import { useQuery } from '@tanstack/react-query';
import { dashboardApi } from '../api/dashboardApi.js';

export function useRealtimeAlerts() {
  return useQuery({
    queryKey: ['realtime-alerts'],
    queryFn: dashboardApi.getAlerts,
  });
}
