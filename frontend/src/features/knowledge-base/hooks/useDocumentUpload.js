import { useMutation, useQueryClient } from "@tanstack/react-query";
import { knowledgeBaseApi } from "../api/knowledgeBaseApi.js";
export function useDocumentUpload() {
  const client=useQueryClient();
  return useMutation({mutationFn:knowledgeBaseApi.uploadDocument,onSettled:async()=>{
    await client.invalidateQueries({queryKey:["knowledge-documents"]});
    await client.invalidateQueries({queryKey:["subscription","usage"]});
  }});
}
