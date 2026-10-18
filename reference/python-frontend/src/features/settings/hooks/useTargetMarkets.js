import { useQuery } from '@tanstack/react-query';
import { companyApi } from '../api/companyApi.js';

export function useTargetMarkets() {
  return useQuery({ queryKey: ['settings-target-markets'], queryFn: companyApi.getTargetMarkets });
}
