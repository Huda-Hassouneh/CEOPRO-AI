import { z } from "zod";

export const RAG_DOCUMENT_EXTENSIONS = [
  ".txt",
  ".md",
  ".pdf",
  ".docx",
  ".xlsx"
] as const;

export const ragDocumentsListQuerySchema = z.object({
  page: z.coerce.number().int().positive("page must be a positive integer").optional()
});

export const ragQuerySchema = z.object({
  query_text: z
    .string({ error: "query_text query parameter is required" })
    .trim()
    .min(1, "query_text cannot be empty")
    .max(2000, "query_text cannot exceed 2000 characters"),
  top_k: z.coerce
    .number()
    .int()
    .positive("top_k must be a positive integer")
    .max(20, "top_k cannot exceed 20")
    .optional(),
  history_json: z.string().optional()
});

const ragDocumentStatusSchema = z
  .string()
  .trim()
  .transform((value) => {
    switch (value.toLowerCase()) {
      case "pending":
        return "Pending";
      case "processed":
        return "Processed";
      case "failed":
        return "Failed";
      default:
        return value;
    }
  })
  .pipe(z.enum(["Pending", "Processed", "Failed"]));

export const ragUploadResponseSchema = z.object({
  document_id: z.string().uuid("AI document_id must be a valid UUID"),
  file_name: z.string().trim().min(1).max(255),
  processed_status: ragDocumentStatusSchema
});

export const ragQueryResponseSchema = z
  .object({
    answer: z.string(),
    sources: z.array(z.record(z.string(), z.unknown())).default([])
  })
  .passthrough();

export type RagUploadResponse = z.infer<typeof ragUploadResponseSchema>;
export type RagQueryResponse = z.infer<typeof ragQueryResponseSchema>;

export type RagUploadInput = {
  tenantId: string;
  userId: string;
  authorization?: string;
  file: {
    originalname: string;
    mimetype: string;
    size: number;
    buffer: Buffer;
  };
};

export type RagQueryInput = {
  tenantId: string;
  queryText: string;
  topK: number;
  historyJson?: string;
  authorization?: string;
};

export type RagDocumentStatus = "Pending" | "Processed" | "Failed";

export type RagServiceError = Error & {
  name: "RagServiceError";
  code:
    | "INVALID_FILE_UPLOAD"
    | "FILE_SIZE_LIMIT_EXCEEDED"
    | "FEATURE_NOT_INCLUDED"
    | "USAGE_EXCEEDED"
    | "STORAGE_EXCEEDED"
    | "MALFORMED_HISTORY_JSON"
    | "NOT_FOUND";
  detail?: unknown;
};

export type RagClientError = Error & {
  name: "RagClientError";
  upstreamStatus?: number;
  kind: "external" | "llm";
};
