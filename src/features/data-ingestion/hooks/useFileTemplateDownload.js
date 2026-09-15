import { useQuery } from '@tanstack/react-query';
import { ingestionApi } from '../api/ingestionApi.js';

export function useFileTemplateDownload() {
  return useQuery({
    queryKey: ['file-template-download'],
    queryFn: ingestionApi.downloadTemplate,
  });
}
