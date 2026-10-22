import { useEffect, useRef } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { marketingApi } from '../api/marketingApi.js';

// Live image-worker capacity (workers, speed, queue wait). Refreshed every minute.
export function useImageCapacity() {
  return useQuery({ queryKey: ['marketing-image-capacity'], queryFn: marketingApi.getImageCapacity, refetchInterval: 60000, retry: false });
}

// The campaign's background image jobs. Polls while any are waiting or being
// made, and refreshes the gallery each time more images are finished.
export function useImageJobs(campaignId) {
  const queryClient = useQueryClient();
  const jobs = useQuery({
    queryKey: ['marketing-image-jobs', campaignId],
    queryFn: () => marketingApi.listImageJobs(campaignId),
    enabled: Boolean(campaignId),
    refetchInterval: (query) => {
      const counts = query.state.data?.counts;
      return counts && counts.QUEUED + counts.RUNNING > 0 ? 5000 : false;
    },
  });
  const completed = jobs.data?.counts?.COMPLETED ?? 0;
  const seen = useRef(completed);
  useEffect(() => {
    if (completed !== seen.current) {
      seen.current = completed;
      queryClient.invalidateQueries({ queryKey: ['marketing-assets', campaignId] });
      queryClient.invalidateQueries({ queryKey: ['marketing-campaign', campaignId] });
    }
  }, [completed, campaignId, queryClient]);
  return jobs;
}

function useJobAction(fn) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: (_data, arg) => {
      const campaignId = typeof arg === 'string' ? arg : arg.campaignId;
      queryClient.invalidateQueries({ queryKey: ['marketing-image-jobs', campaignId] });
      queryClient.invalidateQueries({ queryKey: ['marketing-image-capacity'] });
    },
  });
}

export const useQueueImageBatch = () => useJobAction(({ campaignId, ...options }) => marketingApi.queueImageBatch(campaignId, options));
export const useCancelImageJobs = () => useJobAction((campaignId) => marketingApi.cancelImageJobs(campaignId));
export const useRetryImageJobs = () => useJobAction((campaignId) => marketingApi.retryImageJobs(campaignId));
