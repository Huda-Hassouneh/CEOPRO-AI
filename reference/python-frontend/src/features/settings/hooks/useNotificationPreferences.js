import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useAuthStore } from '../../auth/store/authStore.js';
import { preferencesApi } from '../api/preferencesApi.js';

const keyFor = (companyId, user) => ['notification-preferences', companyId, user?.id || user?.userId || user?.user_id || user?.email];

export function useNotificationPreferences(companyId) {
  const user = useAuthStore((state) => state.user);
  return useQuery({ queryKey: keyFor(companyId, user), queryFn: preferencesApi.getNotificationPreferences });
}

// Saves one change at a time and shows it straight away; a failed save puts
// the stored value back.
export function useUpdateNotificationPreferences(companyId) {
  const user = useAuthStore((state) => state.user);
  const queryClient = useQueryClient();
  const key = keyFor(companyId, user);
  return useMutation({
    mutationFn: preferencesApi.updateNotificationPreferences,
    onMutate: async (patch) => {
      await queryClient.cancelQueries({ queryKey: key });
      const previous = queryClient.getQueryData(key);
      if (previous?.preferences) {
        const next = { ...previous.preferences };
        for (const channel of ['in_app', 'email']) if (patch[channel]) next[channel] = { ...next[channel], ...patch[channel] };
        if (patch.email_frequency) next.email_frequency = patch.email_frequency;
        queryClient.setQueryData(key, { ...previous, preferences: next });
      }
      return { previous };
    },
    onError: (_error, _patch, context) => { if (context?.previous) queryClient.setQueryData(key, context.previous); },
    onSuccess: (data) => queryClient.setQueryData(key, data),
  });
}
