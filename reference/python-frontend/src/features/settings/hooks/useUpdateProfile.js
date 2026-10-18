import { useMutation } from '@tanstack/react-query';
import { profileApi } from '../api/profileApi.js';

export function useUpdateProfile() {
  return useMutation({ mutationFn: profileApi.updateProfile });
}
