import { useQuery } from '@tanstack/react-query';
import { dataConnectionsApi } from '../api/dataConnectionsApi.js';

export function useDataConnections() {
  return useQuery({ queryKey: ['data-connections'], queryFn: dataConnectionsApi.list });
}
