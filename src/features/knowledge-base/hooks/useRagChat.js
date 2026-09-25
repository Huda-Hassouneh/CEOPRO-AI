import { useMutation, useQueryClient } from "@tanstack/react-query";
import { knowledgeBaseApi } from "../api/knowledgeBaseApi.js";

export function useRagChat() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: knowledgeBaseApi.chat,
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["subscription", "usage"] })
  });
}
