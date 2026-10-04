import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useSWRConfig } from "swr";
import { knowledgeBaseApi } from "../api/knowledgeBaseApi.js";

export function useRagChat() {
  const queryClient = useQueryClient();
  const { mutate } = useSWRConfig();

  return useMutation({
    mutationFn: knowledgeBaseApi.chat,

    onSuccess: async () => {
      await Promise.all([
        // Used by FeatureGate / entitlement hooks.
        queryClient.invalidateQueries({
          queryKey: ["subscription", "usage"]
        }),

        // Used by Billing → Feature Usage.
        mutate("subscription-current-usage")
      ]);
    }
  });
}
