import { useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { useAuthStore } from '../auth/store/authStore.js';

// Replaces the session with another company's and drops every cached
// screen, so nothing from the previous company can show in the next one.
export function useOpenWorkspace() {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const setSession = useAuthStore((state) => state.setSession);
  const currentUser = useAuthStore((state) => state.user);
  return (session) => {
    if (!session) return;
    setSession({ ...session, user: { ...session.user, email: session.user.email || currentUser?.email || null } });
    queryClient.clear();
    navigate('/dashboard', { replace: true });
  };
}
