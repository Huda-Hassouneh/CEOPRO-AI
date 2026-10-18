import { z } from "zod";

export const RAG_DOCUMENT_EXTENSIONS = [
  ".txt",
  ".md",
  ".pdf",
  ".docx",
  ".xlsx"
] as const;
// KEEL's upload limit is 2 MiB per document (independent of upstream limits).
export const MAX_RAG_DOCUMENT_SIZE_BYTES = 2 * 1024 * 1024;

export const ragDocumentsListQuerySchema = z.object({
  page: z.coerce
    .number()
    .int()
    .positive("page must be a positive integer")
    .optional(),
  search:z.string().trim().max(200).optional(),
  type:z.string().max(100).optional(),
  sort:z.enum(['newest','oldest']).optional()
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
  history_json: z.string().max(48000).optional(),
  session_id:z.string().uuid().optional(),
  request_id:z.string().uuid().optional(),
  language:z.enum(['en','ar']).optional()
});

const ragDocumentStatusSchema = z
  .string()
  .trim()
  .transform((value) => {
    switch (value.toLowerCase()) {
      case "pending":
        return "Pending";
      case "stored":
        return "Stored";
      case "processed":
        return "Processed";
      case "failed":
        return "Failed";
      default:
        return value;
    }
  })
  .pipe(z.enum(["Pending", "Stored", "Processed", "Failed"]));

export const ragUploadResponseSchema = z.object({
  document_id: z.string().uuid("AI document_id must be a valid UUID"),
  file_name: z.string().trim().min(1).max(255),
  processed_status: ragDocumentStatusSchema
});

export const ragQueryResponseSchema = z
  .object({
    answer: z.string().trim().min(1).max(24000),
    sources: z
      .array(
        z
          .object({
            source_index: z.number().int().nonnegative(),
            document: z.string().min(1).max(512),
            chunk_index: z.number().int().nonnegative(),
            text: z.string().trim().min(1).max(20000),
            score: z.number().finite()
          })
          .passthrough()
      )
      .max(20).default([]),
    token_usage: z.record(z.string(), z.unknown()).optional()
  })
  .passthrough();

export type RagUploadResponse = z.infer<typeof ragUploadResponseSchema>;
export type RagQueryResponse = z.infer<typeof ragQueryResponseSchema>;

export type RagUploadInput = {
  tenantId: string;
  userId: string;
  file: {
    originalname: string;
    mimetype: string;
    size: number;
    buffer: Buffer;
  };
};

export type RagQueryInput = {
  tenantId: string;
  userId: string;
  queryText: string;
  topK: number;
  historyJson?: string;
  sessionId?:string;
  requestId?:string;
  language?:'en'|'ar';
};

export type RagDocumentStatus = "Pending" | "Stored" | "Processed" | "Failed";

export type RagServiceError = Error & {
  name: "RagServiceError";
  code:
    | "INVALID_FILE_UPLOAD"
    | "FILE_SIZE_LIMIT_EXCEEDED"
    | "FEATURE_NOT_INCLUDED"
    | "USAGE_EXCEEDED"
    | "STORAGE_EXCEEDED"
    | "MALFORMED_HISTORY_JSON"
    | "NOT_FOUND"
    | "NO_DOCUMENTS"
    | "DOCUMENT_CONTENT_UNAVAILABLE"
    | "DOCUMENT_DELETE_UNAVAILABLE";
  detail?: unknown;
};

export type RagClientError = Error & {
  name: "RagClientError";
  upstreamStatus?: number;
  kind: "external" | "llm";
};
