import { basename } from "node:path";

export type JsonObject = Record<string, any>;

export type AiServiceError = Error & {
  name: "AiServiceError";
  upstreamStatus?: number;
  kind: "external" | "llm";
};

const AI_SERVICE_URL = (
  process.env.AI_SERVICE_URL || "http://localhost:8000"
).replace(/\/+$/, "");
const USE_AI_MOCKS = process.env.AI_SERVICE_USE_MOCKS === "true";
const DEFAULT_TIMEOUT_MS = 20_000;
const LONG_TIMEOUT_MS = 60_000;

function createAiServiceError(
  message: string,
  upstreamStatus?: number,
  kind: "external" | "llm" = "external"
): AiServiceError {
  const error = new Error(message) as AiServiceError;
  error.name = "AiServiceError";
  error.upstreamStatus = upstreamStatus;
  error.kind = kind;
  return error;
}

export function isAiServiceError(error: unknown): error is AiServiceError {
  return (
    error instanceof Error &&
    error.name === "AiServiceError" &&
    "kind" in error &&
    (error.kind === "external" || error.kind === "llm")
  );
}

function safeUploadName(fileName: string): string {
  const safeBaseName = basename(fileName).replace(
    /[\x00-\x1f<>:"\/\\|?*]+/g,
    "_"
  );
  return safeBaseName.slice(0, 255) || "upload";
}

function aiUrl(pathname: string): URL {
  return new URL(pathname, `${AI_SERVICE_URL}/`);
}

async function fetchWithTimeout(
  input: string | URL,
  init: RequestInit = {},
  timeoutMs = DEFAULT_TIMEOUT_MS
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
      throw createAiServiceError(
        `AI service request timed out after ${timeoutMs} ms.`
      );
    }
    throw error;
  } finally {
    clearTimeout(timeout);
  }
}

async function parseJsonResponse(response: Response): Promise<JsonObject> {
  try {
    const data = await response.json();
    if (!data || typeof data !== "object" || Array.isArray(data)) {
      throw new Error("Response body must be a JSON object.");
    }
    return data as JsonObject;
  } catch {
    throw createAiServiceError(
      "AI service returned an invalid JSON response.",
      response.status
    );
  }
}

async function requestAiJson(
  url: URL,
  init: RequestInit,
  options: {
    timeoutMs?: number;
    serviceName: string;
    mapServerErrorsToLlmFailure?: boolean;
  }
): Promise<JsonObject> {
  const response = await fetchWithTimeout(
    url,
    init,
    options.timeoutMs ?? DEFAULT_TIMEOUT_MS
  );
  if (!response.ok) {
    const isLlmFailure =
      options.mapServerErrorsToLlmFailure &&
      (response.status === 500 ||
        response.status === 502 ||
        response.status === 503);
    throw createAiServiceError(
      `${options.serviceName} returned HTTP ${response.status}.`,
      response.status,
      isLlmFailure ? "llm" : "external"
    );
  }
  return parseJsonResponse(response);
}

function mockExtractionData(tenantId: string, fileName: string): JsonObject {
  return {
    job_id: "a5d8b76e-34e8-48b2-b5e1-88981f2c24ef",
    template_mode: "best-effort mapping",
    is_template_compliant: false,
    rows_processed: 150,
    rows_partial: 12,
    rows_failed: 3,
    data_loss_pct: 2.0,
    header_coverage_ratio: 0.88,
    minio_object_key: `raw-uploads/tenant-${tenantId.slice(0, 8)}/${fileName}`,
    row_outcomes: [],
    promotion: {
      rows_promoted: 135,
      rows_skipped_incomplete: 12,
      rows_failed: 3,
      products_created: 18,
      errors: []
    },
    currency_resolution: {
      currency: "USD",
      needs_confirmation: true
    }
  };
}

const MOCK_RAG_RESPONSE: JsonObject = {
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

const MOCK_RAG_CHUNKS: Record<string, JsonObject> = {
  "c1f7a3b2-9d4e-48c5-a2b1-3e6f9a8d7c4b": {
    chunk_id: "c1f7a3b2-9d4e-48c5-a2b1-3e6f9a8d7c4b",
    text_content:
      "The expected Q3 marketing budget is strictly capped at $150,000. This includes $50,000 allocated for digital ad spend across social channels, $75,000 for regional event sponsorships, and $25,000 reserved for influencer partnerships and affiliate programs.",
    file_name: "2026_Q3_Marketing_Strategy.pdf"
  },
  "e8d9c0b1-4a5f-42e3-b6c7-1d2a3f4e5b6c": {
    chunk_id: "e8d9c0b1-4a5f-42e3-b6c7-1d2a3f4e5b6c",
    text_content:
      "MinIO utilizes erasure coding rather than traditional data replication to ensure high resilience and protect against multiple drive failures. This allows the storage cluster to lose up to half of its drives and still reconstruct the missing data automatically during data ingestion pipelines.",
    file_name: "System_Architecture_Guide.pdf"
  }
};

export function isFeaturesAiMockModeEnabled(): boolean {
  return USE_AI_MOCKS;
}

export function getMockRagChunk(chunkId: string): JsonObject | null {
  return MOCK_RAG_CHUNKS[chunkId] ?? null;
}

export async function uploadExtractionFileToAi(input: {
  tenantId: string;
  file: {
    originalname: string;
    mimetype: string;
    buffer: Buffer;
  };
  authorization?: string;
}): Promise<JsonObject> {
  const fileName = safeUploadName(input.file.originalname);

  if (USE_AI_MOCKS) {
    return mockExtractionData(input.tenantId, fileName);
  }

  const formData = new FormData();
  formData.append(
    "file",
    new Blob([new Uint8Array(input.file.buffer)], { type: input.file.mimetype }),
    fileName
  );

  return requestAiJson(
    aiUrl("extraction/upload"),
    {
      method: "POST",
      headers: input.authorization
        ? { Authorization: input.authorization }
        : {},
      body: formData
    },
    {
      timeoutMs: LONG_TIMEOUT_MS,
      serviceName: "AI extraction service"
    }
  );
}

export async function queryRagAi(input: {
  queryText: string;
  topK: number;
  historyJson?: string;
  authorization?: string;
}): Promise<JsonObject> {
  if (USE_AI_MOCKS) {
    return MOCK_RAG_RESPONSE;
  }

  const url = aiUrl("rag/query");
  url.searchParams.set("query_text", input.queryText);
  url.searchParams.set("top_k", String(input.topK));
  if (input.historyJson) url.searchParams.set("history_json", input.historyJson);

  return requestAiJson(
    url,
    {
      method: "POST",
      headers: input.authorization
        ? { Authorization: input.authorization }
        : {}
    },
    {
      timeoutMs: LONG_TIMEOUT_MS,
      serviceName: "RAG AI service",
      mapServerErrorsToLlmFailure: true
    }
  );
}
