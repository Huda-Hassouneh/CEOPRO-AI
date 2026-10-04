import { randomUUID } from "node:crypto";
import { basename } from "node:path";
import {
  ragQueryResponseSchema,
  ragUploadResponseSchema,
  type RagClientError,
  type RagQueryResponse,
  type RagUploadResponse
} from "../types/rag.types.js";

const AI_SERVICE_URL = (
  process.env.AI_SERVICE_URL || "http://localhost:8000"
).replace(/\/+$/, "");

/**
 * RAG stays in mock mode by default while the AI endpoint is being integrated.
 * Set RAG_AI_USE_MOCKS=false to call the real CEOPRO AI service.
 */
const USE_RAG_AI_MOCKS =
  (process.env.RAG_AI_USE_MOCKS ?? "true").trim().toLowerCase() === "true";

const DEFAULT_TIMEOUT_MS = 20_000;
const UPLOAD_TIMEOUT_MS = 60_000;

function createRagClientError(
  message: string,
  upstreamStatus?: number,
  kind: "external" | "llm" = "external"
): RagClientError {
  const error = new Error(message) as RagClientError;
  error.name = "RagClientError";
  error.upstreamStatus = upstreamStatus;
  error.kind = kind;
  return error;
}

export function isRagClientError(error: unknown): error is RagClientError {
  return (
    error instanceof Error &&
    error.name === "RagClientError" &&
    "kind" in error
  );
}

export function isRagAiMockModeEnabled(): boolean {
  return USE_RAG_AI_MOCKS;
}

function safeUploadName(fileName: string): string {
  const safeBaseName = basename(fileName).replace(
    /[\x00-\x1f<>:"/\\|?*]+/g,
    "_"
  );
  return safeBaseName.slice(0, 255) || "upload";
}

function aiUrl(pathname: string): URL {
  return new URL(pathname, `${AI_SERVICE_URL}/`);
}

async function fetchWithTimeout(
  input: string | URL,
  init: RequestInit,
  timeoutMs: number
): Promise<Response> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);

  try {
    return await fetch(input, {
      ...init,
      signal: controller.signal
    });
  } catch (error) {
    if (error instanceof Error && error.name === "AbortError") {
      throw createRagClientError(
        `RAG AI service request timed out after ${timeoutMs} ms.`
      );
    }
    throw error;
  } finally {
    clearTimeout(timeout);
  }
}

async function parseJsonObject(response: Response): Promise<unknown> {
  try {
    return await response.json();
  } catch {
    throw createRagClientError(
      "RAG AI service returned an invalid JSON response.",
      response.status
    );
  }
}

async function requestJson(
  url: URL,
  init: RequestInit,
  options: {
    timeoutMs: number;
    mapServerErrorsToLlmFailure?: boolean;
  }
): Promise<unknown> {
  const response = await fetchWithTimeout(url, init, options.timeoutMs);

  if (!response.ok) {
    const isLlmFailure =
      options.mapServerErrorsToLlmFailure &&
      [500, 502, 503].includes(response.status);

    throw createRagClientError(
      `RAG AI service returned HTTP ${response.status}.`,
      response.status,
      isLlmFailure ? "llm" : "external"
    );
  }

  return parseJsonObject(response);
}

function mockRagUpload(fileName: string): RagUploadResponse {
  return {
    document_id: randomUUID(),
    file_name: fileName,
    processed_status: "Pending"
  };
}

const MOCK_RAG_RESPONSE: RagQueryResponse = {
  totalTokens: 400,
  answer:
    "MinIO utilizes erasure coding rather than traditional data replication to ensure high resilience and protect against multiple drive failures.",
  sources: [
    {
      source_index: 1,
      chunk_id: "c1f7a3b2-9d4e-48c5-a2b1-3e6f9a8d7c4b",
      score: 0.94
    },
    {
      source_index: 2,
      chunk_id: "e8d9c0b1-4a5f-42e3-b6c7-1d2a3f4e5b6c",
      score: 0.88
    }
  ]
};

const MOCK_RAG_CHUNKS: Record<string, Record<string, unknown>> = {
  "c1f7a3b2-9d4e-48c5-a2b1-3e6f9a8d7c4b": {
    chunk_id: "c1f7a3b2-9d4e-48c5-a2b1-3e6f9a8d7c4b",
    text_content:
      "The expected Q3 marketing budget is strictly capped at $150,000.",
    file_name: "2026_Q3_Marketing_Strategy.pdf"
  },
  "e8d9c0b1-4a5f-42e3-b6c7-1d2a3f4e5b6c": {
    chunk_id: "e8d9c0b1-4a5f-42e3-b6c7-1d2a3f4e5b6c",
    text_content:
      "MinIO utilizes erasure coding rather than traditional data replication to ensure high resilience.",
    file_name: "System_Architecture_Guide.pdf"
  }
};

export function getMockRagChunk(
  chunkId: string
): Record<string, unknown> | null {
  return MOCK_RAG_CHUNKS[chunkId] ?? null;
}

export async function uploadRagDocumentToAi(input: {
  file: {
    originalname: string;
    mimetype: string;
    buffer: Buffer;
  };
  authorization?: string;
}): Promise<RagUploadResponse> {
  const fileName = safeUploadName(input.file.originalname);

  if (USE_RAG_AI_MOCKS) {
    return mockRagUpload(fileName);
  }

  const formData = new FormData();
  formData.append(
    "file",
    new Blob([new Uint8Array(input.file.buffer)], {
      type: input.file.mimetype || "application/octet-stream"
    }),
    fileName
  );

  const raw = await requestJson(
    aiUrl("rag/documents"),
    {
      method: "POST",
      headers: input.authorization
        ? { Authorization: input.authorization }
        : {},
      body: formData
    },
    { timeoutMs: UPLOAD_TIMEOUT_MS }
  );

  const parsed = ragUploadResponseSchema.safeParse(raw);
  if (!parsed.success) {
    throw createRagClientError(
      "RAG AI upload response did not match the documented contract."
    );
  }

  return parsed.data;
}

export async function queryRagAi(input: {
  queryText: string;
  topK: number;
  historyJson?: string;
  authorization?: string;
}): Promise<RagQueryResponse> {
  if (USE_RAG_AI_MOCKS) {
    return MOCK_RAG_RESPONSE;
  }

  const url = aiUrl("rag/query");
  url.searchParams.set("query_text", input.queryText);
  url.searchParams.set("top_k", String(input.topK));
  if (input.historyJson) {
    url.searchParams.set("history_json", input.historyJson);
  }

  const raw = await requestJson(
    url,
    {
      method: "POST",
      headers: input.authorization
        ? { Authorization: input.authorization }
        : {}
    },
    {
      timeoutMs: DEFAULT_TIMEOUT_MS,
      mapServerErrorsToLlmFailure: true
    }
  );

  const parsed = ragQueryResponseSchema.safeParse(raw);
  if (!parsed.success) {
    throw createRagClientError(
      "RAG AI query response did not match the expected contract."
    );
  }

  return parsed.data;
}
