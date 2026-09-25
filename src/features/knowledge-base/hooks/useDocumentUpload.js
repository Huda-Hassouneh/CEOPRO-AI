import { useMutation } from "@tanstack/react-query";
import { knowledgeBaseApi } from "../api/knowledgeBaseApi.js";

export function useDocumentUpload() {
  return useMutation({
    mutationFn: knowledgeBaseApi.uploadDocument
  });
}
