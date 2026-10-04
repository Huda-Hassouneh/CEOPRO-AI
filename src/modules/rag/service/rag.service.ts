import { extname } from "node:path";
import {
  assertFeatureCapacity,
  getRemainingUsage,
  incrementUsage
} from "../../features/repo/usage.repo.js";
import {
  getMockRagChunk,
  isRagAiMockModeEnabled,
  queryRagAi,
  uploadRagDocumentToAi
} from "../client/rag.client.js";
import {
  countRagDocuments,
  getRagChunk,
  listRagDocuments,
  saveUploadedRagDocument
} from "../repo/rag.repo.js";
import {
  RAG_DOCUMENT_EXTENSIONS,
  type RagDocumentStatus,
  type RagQueryInput,
  type RagServiceError,
  type RagUploadInput
} from "../types/rag.types.js";

const MAX_UPLOAD_SIZE_BYTES = Number(
  process.env.MAX_UPLOAD_BYTES || 10 * 1024 * 1024
);
const ALLOWED_EXTENSIONS = new Set<string>(RAG_DOCUMENT_EXTENSIONS);

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

function extractTotalTokens(data: Record<string, any>): number {
  const explicitTotal = Number(
    data.totalTokens ?? data.total_tokens ?? data.usage?.total_tokens
  );
  if (Number.isFinite(explicitTotal) && explicitTotal >= 0) {
    return Math.floor(explicitTotal);
  }

  const inputTokens = Number(
    data.inputTokens ?? data.input_tokens ?? data.usage?.input_tokens ?? 0
  );
  const outputTokens = Number(
    data.outputTokens ?? data.output_tokens ?? data.usage?.output_tokens ?? 0
  );
  const total = inputTokens + outputTokens;
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

  if (
    extraction.remaining !== null &&
    kbUsed > Number(extraction.remaining)
  ) {
    throw createRagServiceError(
      "USAGE_EXCEEDED",
      "This upload exceeds the remaining document extraction quota.",
      {
        requested: kbUsed,
        remaining: extraction.remaining,
        unit: "KB"
      }
    );
  }

  const storageMb = input.fileSizeBytes / 1024 ** 2;
  const storage = await assertFeatureCapacity({
    tenantId: input.tenantId,
    featureCode: "document_storage_mb",
    additionalAmount: storageMb
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
        requested: storageMb,
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
      `Allowed RAG document extensions are ${RAG_DOCUMENT_EXTENSIONS.join(
        ", "
      )}.`
    );
  }

  if (!Number.isFinite(input.file.size) || input.file.size <= 0) {
    throw createRagServiceError(
      "INVALID_FILE_UPLOAD",
      "The uploaded file is empty or has an invalid size."
    );
  }

  if (input.file.size > MAX_UPLOAD_SIZE_BYTES) {
    throw createRagServiceError(
      "FILE_SIZE_LIMIT_EXCEEDED",
      `File exceeds the ${Math.floor(
        MAX_UPLOAD_SIZE_BYTES / 1024 / 1024
      )} MB size limit.`
    );
  }

  const { kbUsed } = await assertUploadEntitlements({
    tenantId: input.tenantId,
    fileSizeBytes: input.file.size
  });

  const ai = await uploadRagDocumentToAi({
    file: {
      originalname: input.file.originalname,
      mimetype: input.file.mimetype,
      buffer: input.file.buffer
    },
    authorization: input.authorization
  });

  await saveUploadedRagDocument({
    tenantId: input.tenantId,
    userId: input.userId,
    documentId: ai.document_id,
    fileName: ai.file_name,
    fileSizeBytes: input.file.size,
    contentType: input.file.mimetype || "application/octet-stream",
    processedStatus: ai.processed_status
  });

  await incrementUsage(input.tenantId, "document_extraction", kbUsed);

  return {
    document_id: ai.document_id,
    file_name: ai.file_name,
    processed_status: ai.processed_status
  };
}

export async function getRagDocuments(input: {
  tenantId: string;
  page: number;
  pageSize?: number;
}) {
  const pageSize = input.pageSize ?? 3;
  const [documents, total] = await Promise.all([
    listRagDocuments({
      tenantId: input.tenantId,
      page: input.page,
      pageSize
    }),
    countRagDocuments(input.tenantId)
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

  let historyJson = input.historyJson;
  if (historyJson !== undefined) {
    try {
      const parsed = JSON.parse(historyJson);
      if (!Array.isArray(parsed)) {
        throw new Error("history_json must decode to an array.");
      }
      historyJson = JSON.stringify(parsed);
    } catch {
      throw createRagServiceError(
        "MALFORMED_HISTORY_JSON",
        "history_json must be a valid JSON array string."
      );
    }
  }

  const data = await queryRagAi({
    queryText: input.queryText,
    topK: input.topK,
    historyJson,
    authorization: input.authorization
  });

  const totalTokens = extractTotalTokens(data);
  if (totalTokens > 0) {
    await incrementUsage(input.tenantId, "rag_assistant", totalTokens);
  }

  return {
    answer: data.answer,
    sources: Array.isArray(data.sources) ? data.sources : []
  };
}

export async function getRagChunkDetail(tenantId: string, chunkId: string) {
  if (isRagAiMockModeEnabled()) {
    const mocked = getMockRagChunk(chunkId);
    if (!mocked) {
      throw createRagServiceError(
        "NOT_FOUND",
        `Chunk ${chunkId} was not found.`
      );
    }
    return mocked;
  }

  const chunk = await getRagChunk(tenantId, chunkId);
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
