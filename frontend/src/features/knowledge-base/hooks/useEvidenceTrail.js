import { useQuery } from "@tanstack/react-query";
import { knowledgeBaseApi } from "../api/knowledgeBaseApi.js";
import {useAuthStore} from '../../auth/store/authStore.js';

export const useEvidenceChunk = (chunkId) => {
  const companyId=useAuthStore(state=>state.tenantId);
  const userId=useAuthStore(state=>state.user?.userId??state.user?.user_id??state.user?.id);
  return useQuery({
    queryKey: ["rag_chunk", companyId,userId,chunkId],
    queryFn: ({ signal }) => knowledgeBaseApi.getChunkDetail(chunkId, signal),
    enabled: !!chunkId, // Only execute if a chunkId is provided
    staleTime: 0,
    gcTime:0
  });
};
