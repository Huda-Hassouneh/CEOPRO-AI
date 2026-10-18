import { useAuthStore } from '../../auth/store/authStore.js';
import { useQuery } from '@tanstack/react-query';
import { securityApi } from '../api/securityApi.js';

export function useActiveSessions() {
  const user = useAuthStore((state) => state.user);
  return useQuery({ queryKey: ['active-sessions', user?.id || user?.userId || user?.user_id || user?.email], queryFn: securityApi.getSessions });
}
