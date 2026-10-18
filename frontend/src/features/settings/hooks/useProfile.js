import { useQuery } from '@tanstack/react-query';
import { profileApi } from '../api/profileApi.js';

export function useProfile(user) {
  return useQuery({ queryKey: ['settings-profile', user], queryFn: () => profileApi.getProfile({ user }) });
}
