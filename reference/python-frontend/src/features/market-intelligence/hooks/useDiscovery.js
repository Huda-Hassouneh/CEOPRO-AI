import { useEffect } from 'react';
import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { discoveryApi, RUN_ACTIVE } from '../api/discoveryApi.js';

const COMPETITOR_KEYS = [['discovery-competitors'], ['competitor-landscape'], ['competitors'], ['command-center']];

export function useDiscoveryStatus() {
  return useQuery({ queryKey: ['discovery-status'], queryFn: discoveryApi.status });
}

// Follows the latest run while it is queued or running, then refreshes
// everything that shows competitors.
export function useDiscoveryRun(runId) {
  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey: ['discovery-run', runId],
    queryFn: () => discoveryApi.run(runId),
    enabled: Boolean(runId),
    refetchInterval: (q) => (RUN_ACTIVE.includes(q.state.data?.status) || !q.state.data ? 2000 : false),
  });
  const status = query.data?.status;
  useEffect(() => {
    if (status && !RUN_ACTIVE.includes(status)) {
      COMPETITOR_KEYS.forEach((queryKey) => queryClient.invalidateQueries({ queryKey }));
      queryClient.invalidateQueries({ queryKey: ['discovery-status'] });
    }
  }, [status, queryClient]);
  return query;
}

export function useStartDiscovery() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: discoveryApi.start,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['discovery-status'] }),
  });
}

export const COMPETITOR_PAGE_SIZE = 100;

// Pages of COMPETITOR_PAGE_SIZE; "Show more" loads the next one. data has the
// same shape as one response, with every loaded page's competitors.
export function useDiscoveredCompetitors(filters) {
  return useInfiniteQuery({
    queryKey: ['discovery-competitors', filters],
    queryFn: ({ pageParam }) => discoveryApi.competitors({ ...filters, limit: COMPETITOR_PAGE_SIZE, offset: pageParam }),
    initialPageParam: 0,
    getNextPageParam: (last) => {
      const next = (last.offset || 0) + (last.competitors?.length || 0);
      return next < (last.matching ?? 0) && last.competitors?.length ? next : undefined;
    },
    select: (data) => ({ ...data.pages[0], competitors: data.pages.flatMap((page) => page.competitors) }),
    placeholderData: (previous) => previous,
  });
}

export function useTrackCompetitor() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, track }) => (track ? discoveryApi.track(id) : discoveryApi.untrack(id)),
    onSuccess: () => COMPETITOR_KEYS.forEach((queryKey) => queryClient.invalidateQueries({ queryKey })),
  });
}
