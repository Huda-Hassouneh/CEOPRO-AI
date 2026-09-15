import { useQuery } from '@tanstack/react-query';
import { dataConnectionsApi } from '../api/dataConnectionsApi.js';

export function useDataConnections(companyId) {
  return useQuery({
    queryKey: ['data-connections', companyId],
    queryFn: () => dataConnectionsApi.list({ companyId }),
  });
}
