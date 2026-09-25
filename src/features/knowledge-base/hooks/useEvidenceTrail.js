import { useQuery } from "@tanstack/react-query";
import { knowledgeBaseApi } from "../api/knowledgeBaseApi.js";

export const useEvidenceChunk = (chunkId) => {
  return useQuery({
    queryKey: ["rag_chunk", chunkId],
    queryFn: ({ signal }) => knowledgeBaseApi.getChunkDetail(chunkId, signal),
    enabled: !!chunkId, // Only execute if a chunkId is provided
    staleTime: 5 * 60 * 1000 // Cache for 5 minutes
  });
};
