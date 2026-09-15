import { useMutation } from '@tanstack/react-query';
import { marketingApi } from '../api/marketingApi.js';

export function useMarketingImageGeneration() {
  return useMutation({
    mutationFn: marketingApi.generateImage,
  });
}
