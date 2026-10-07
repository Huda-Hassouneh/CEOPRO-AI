import { randomUUID } from "node:crypto";
import { extname } from "node:path";
import { z } from "zod";
import { safeUploadName } from "../../dataconnection/types/dataconnection.validation.js";
import {
  assertFeatureCapacity,
  getRemainingUsage,
  incrementUsage
} from "../../features/repo/usage.repo.js";
import { queryRagAi, type RagAiDocument } from "../client/rag.client.js";
import {
  countRagDocuments,
  getRagChunk,
  getRagQueryDocuments,
  listRagDocuments,
  persistRagQuerySources,
  saveUploadedRagDocument
} from "../repo/rag.repo.js";
import {
  MAX_RAG_DOCUMENT_SIZE_BYTES,
  RAG_DOCUMENT_EXTENSIONS,
  type RagDocumentStatus,
  type RagQueryInput,
  type RagServiceError,
  type RagUploadInput
} from "../types/rag.types.js";

const ALLOWED_EXTENSIONS = new Set<string>(RAG_DOCUMENT_EXTENSIONS);
const MAX_QUERY_DOCUMENTS = 10;
const historySchema = z.array(
  z.object({
    role: z.enum(["system", "user", "assistant"]),
    content: z.string()
  })
);

function createRagServiceError(
  code: RagServiceError["code"],
  message: string,
  detail?: unknown
): RagServiceError {
  const error = new Error(message) as RagServiceError;
  error.name = "RagServiceError";
  error.code = code;
  error.detail = detail;
  return error;
}

export function isRagServiceError(error: unknown): error is RagServiceError {
  return error instanceof Error && error.name === "RagServiceError";
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function extractTotalTokens(data: {
  token_usage?: Record<string, unknown>;
}): number {
  const usage = data.token_usage;
  const explicit = Number(
    usage?.total_tokens ?? usage?.totalTokens ?? usage?.total
  );
  if (Number.isFinite(explicit) && explicit >= 0) return Math.floor(explicit);

  const input = Number(usage?.input_tokens ?? usage?.prompt_tokens ?? 0);
  const output = Number(usage?.output_tokens ?? usage?.completion_tokens ?? 0);
  const total = input + output;
  return Number.isFinite(total) && total > 0 ? Math.floor(total) : 0;
}

async function assertUploadEntitlements(input: {
  tenantId: string;
  fileSizeBytes: number;
}) {
  const kbUsed = Math.max(1, Math.ceil(input.fileSizeBytes / 1024));
  const extraction = await getRemainingUsage(
    input.tenantId,
    "document_extraction"
  );
  if (!extraction) {
    throw createRagServiceError(
      "FEATURE_NOT_INCLUDED",
      "Document extraction is not available for this subscription."
    );
  }
  if (
    extraction.isExceeded ||
    (extraction.remaining !== null && Number(extraction.remaining) <= 0)
  ) {
    throw createRagServiceError(
      "USAGE_EXCEEDED",
      "Document extraction quota has been reached.",
      {
        current_usage: extraction.currentUsage,
        limit: extraction.limit,
        remaining: 0,
        unit: "KB"
      }
    );
  }
  if (extraction.remaining !== null && kbUsed > Number(extraction.remaining)) {
    throw createRagServiceError(
      "USAGE_EXCEEDED",
      "This upload exceeds the remaining document extraction quota.",
      { requested: kbUsed, remaining: extraction.remaining, unit: "KB" }
    );
  }

  const storage = await assertFeatureCapacity({
    tenantId: input.tenantId,
    featureCode: "document_storage_mb",
    additionalAmount: input.fileSizeBytes / 1024 ** 2
  });
  if (!storage.allowed) {
    if (storage.reason === "FEATURE_NOT_INCLUDED") {
      throw createRagServiceError(
        "FEATURE_NOT_INCLUDED",
        "Document storage is not available for this subscription."
      );
    }
    throw createRagServiceError(
      "STORAGE_EXCEEDED",
      "This upload exceeds the available document storage capacity.",
      {
        feature_code: "document_storage_mb",
        reason: "CAPACITY_REACHED",
        current_usage: storage.entitlement.currentUsage,
        limit: storage.entitlement.limit,
        requested: input.fileSizeBytes / 1024 ** 2,
        remaining: storage.entitlement.remaining,
        unit: "MB"
      }
    );
  }
  return { kbUsed };
}

export async function uploadRagDocument(input: RagUploadInput) {
  const extension = extname(input.file.originalname).toLowerCase();
  if (!ALLOWED_EXTENSIONS.has(extension)) {
    throw createRagServiceError(
      "INVALID_FILE_UPLOAD",
      `Allowed RAG document extensions are ${RAG_DOCUMENT_EXTENSIONS.join(", ")}.`
    );
  }
  if (!Number.isFinite(input.file.size) || input.file.size <= 0) {
    throw createRagServiceError(
      "INVALID_FILE_UPLOAD",
      "The uploaded file is empty or has an invalid size."
    );
  }
  if (input.file.size > MAX_RAG_DOCUMENT_SIZE_BYTES) {
    throw createRagServiceError(
      "FILE_SIZE_LIMIT_EXCEEDED",
      "RAG documents must not exceed 10 MB."
    );
  }

  const { kbUsed } = await assertUploadEntitlements({
    tenantId: input.tenantId,
    fileSizeBytes: input.file.size
  });
  const documentId = randomUUID();
  const fileName = safeUploadName(input.file.originalname);

  await saveUploadedRagDocument({
    tenantId: input.tenantId,
    userId: input.userId,
    documentId,
    fileName,
    fileSizeBytes: input.file.size,
    contentType: input.file.mimetype || "application/octet-stream",
    sourceFileContent: input.file.buffer,
    processedStatus: "Processed"
  });
  await incrementUsage(input.tenantId, "document_extraction", kbUsed);

  return {
    document_id: documentId,
    file_name: fileName,
    processed_status: "Processed" as RagDocumentStatus
  };
}

export async function getRagDocuments(input: {
  tenantId: string;
  userId: string;
  page: number;
  pageSize?: number;
}) {
  const pageSize = input.pageSize ?? 3;
  const [documents, total] = await Promise.all([
    listRagDocuments({
      tenantId: input.tenantId,
      userId: input.userId,
      page: input.page,
      pageSize
    }),
    countRagDocuments({ tenantId: input.tenantId, userId: input.userId })
  ]);

  return {
    documents: documents.map((document) => ({
      ...document,
      file_size_bytes: document.file_size_bytes.toString()
    })),
    pagination: {
      page: input.page,
      pageSize,
      total,
      totalPages: Math.ceil(total / pageSize)
    }
  };
}

export async function queryRag(input: RagQueryInput) {
  const usage = await getRemainingUsage(input.tenantId, "rag_assistant");
  if (!usage) {
    throw createRagServiceError(
      "FEATURE_NOT_INCLUDED",
      "RAG assistant is not available for this subscription."
    );
  }
  if (
    usage.isExceeded ||
    (usage.remaining !== null && Number(usage.remaining) <= 0)
  ) {
    throw createRagServiceError(
      "USAGE_EXCEEDED",
      "RAG token quota has been reached.",
      {
        current_usage: usage.currentUsage,
        limit: usage.limit,
        remaining: 0
      }
    );
  }

  let history: Array<{ role: "system" | "user" | "assistant"; content: string }> | null = null;
  if (input.historyJson !== undefined) {
    try {
      const parsed = JSON.parse(input.historyJson) as unknown;
      const result = historySchema.safeParse(parsed);
      if (!result.success) throw new Error("history_json has an invalid shape.");
      history = result.data;
    } catch {
      throw createRagServiceError(
        "MALFORMED_HISTORY_JSON",
        "history_json must be a valid array of role/content messages."
      );
    }
  }

  const storedDocuments = await getRagQueryDocuments({
    tenantId: input.tenantId,
    userId: input.userId,
    limit: MAX_QUERY_DOCUMENTS
  });
  const aiDocuments: RagAiDocument[] = [];
  const documentByAiName = new Map<
    string,
    { documentId: string; fileName: string }
  >();

  for (const document of storedDocuments) {
    const fileName = document.file_name;
    const extension = extname(fileName).toLowerCase();
    // The model identifies citations by file name. Include CEOPRO's document ID
    // so tenants can safely upload files with duplicate display names.
    const aiFileName = `${document.document_id}_${fileName}`;
    const content = document.source_file_content
      ? Buffer.from(document.source_file_content)
      : null;

    if (content && [".txt", ".md"].includes(extension)) {
      const text = content.toString("utf8").replace(/^\uFEFF/, "").trim();
      if (!text) continue;
      aiDocuments.push({ file_name: aiFileName, text });
      documentByAiName.set(aiFileName, {
        documentId: document.document_id,
        fileName
      });
      continue;
    }

    if (content) {
      aiDocuments.push({
        file_name: aiFileName,
        content_base64: content.toString("base64")
      });
      documentByAiName.set(aiFileName, {
        documentId: document.document_id,
        fileName
      });
      continue;
    }

    const storedText = document.rag_document_chunks
      .map((chunk) => chunk.chunk_text_content)
      .filter(Boolean)
      .join("\n\n")
      .trim();
    if (storedText) {
      const chunkSourceName = `${aiFileName}.md`;
      aiDocuments.push({ file_name: chunkSourceName, text: storedText });
      documentByAiName.set(chunkSourceName, {
        documentId: document.document_id,
        fileName
      });
    }
  }

  if (aiDocuments.length === 0) {
    throw createRagServiceError(
      "NO_DOCUMENTS",
      "Upload at least one processed RAG document before asking a question."
    );
  }

  const data = await queryRagAi({
    documents: aiDocuments,
    queryText: input.queryText,
    topK: input.topK,
    history
  });

  const sourceMappings = data.sources.map((source) => {
    const document = documentByAiName.get(source.document);
    return document
      ? { documentId: document.documentId, text: source.text }
      : null;
  });
  const persistableSources = sourceMappings.flatMap((source) =>
    source ? [source] : []
  );
  const storedSources = persistableSources.length
    ? await persistRagQuerySources({
        tenantId: input.tenantId,
        userId: input.userId,
        sources: persistableSources
      })
    : [];

  let storedIndex = 0;
  const sources = data.sources.map((source, index) => {
    const sourceMapping = sourceMappings[index];
    const stored = sourceMapping ? storedSources[storedIndex++] : undefined;
    const document = documentByAiName.get(source.document);
    return {
      ...source,
      document: document?.fileName ?? source.document,
      document_id: document?.documentId ?? null,
      chunk_id: stored?.chunkId ?? null
    };
  });

  const totalTokens = extractTotalTokens(data);
  if (totalTokens > 0) {
    await incrementUsage(input.tenantId, "rag_assistant", totalTokens);
  }

  return { answer: data.answer, sources };
}

export async function getRagChunkDetail(
  tenantId: string,
  userId: string,
  chunkId: string
) {
  const chunk = await getRagChunk({ tenantId, userId, chunkId });
  if (!chunk) {
    throw createRagServiceError(
      "NOT_FOUND",
      "Citation chunk not found or access denied."
    );
  }
  return {
    chunk_id: chunk.chunk_id,
    text_content: chunk.chunk_text_content,
    file_name: chunk.rag_documents_metadata?.file_name || "Unknown File"
  };
}
