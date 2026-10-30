import { useQuery } from '@tanstack/react-query';
import { dataConnectionsApi } from '../api/dataConnectionsApi.js';

export function useDataConnections({ pollWhileSyncQueued = false } = {}) {
  return useQuery({
    queryKey: ['data-connections'],
    queryFn: dataConnectionsApi.list,
    refetchInterval: (query) => {
      const running = query.state.data?.connectedSources?.some((source) =>
        ['QUEUED', 'PROCESSING', 'RUNNING'].includes(source.last_run?.status));
      return pollWhileSyncQueued || running ? 2000 : false;
    },
  });
}
