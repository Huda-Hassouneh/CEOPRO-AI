import { useQuery } from '@tanstack/react-query';
import { companyApi } from '../api/companyApi.js';

export function useCompany(context) {
  return useQuery({ queryKey: ['settings-company', context], queryFn: () => companyApi.getCompany(context) });
}
