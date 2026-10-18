import { useAuthStore } from '../../auth/store/authStore.js';
import { useQuery } from '@tanstack/react-query';
import { preferencesApi } from '../api/preferencesApi.js';

export function useNotificationPreferences(companyId) {
  const user = useAuthStore((state) => state.user);
  return useQuery({ queryKey: ['notification-preferences', companyId, user?.id || user?.userId || user?.user_id || user?.email], queryFn: preferencesApi.getNotificationPreferences });
}
