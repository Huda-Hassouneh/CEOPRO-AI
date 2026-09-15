import { useMutation } from '@tanstack/react-query';
import { competitorsApi } from '../api/competitorsApi.js';

export function useAddCompetitor() {
  return useMutation({
    mutationFn: competitorsApi.create,
  });
}
