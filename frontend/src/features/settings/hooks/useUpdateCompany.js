import { useMutation, useQueryClient } from '@tanstack/react-query';
import { companyApi } from '../api/companyApi.js';

export function useUpdateCompany() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: companyApi.updateCompany,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['settings-company'] });
    },
  });
}
