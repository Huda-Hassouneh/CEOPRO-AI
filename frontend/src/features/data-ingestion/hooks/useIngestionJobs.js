import { useQuery } from '@tanstack/react-query';
import { ingestionApi } from '../api/ingestionApi.js';

export function useIngestionJobs() {
  return useQuery({
    queryKey: ['ingestion-jobs'],
    queryFn: ingestionApi.listJobs,
  });
}
