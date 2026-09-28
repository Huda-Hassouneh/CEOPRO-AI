import { Response as ExpressResponse } from "express";
import { basename } from "node:path";
import {
  documentsRepo,
  getRemainingUsage,
  incrementUsage
} from "../repo/usage.repo.js";
import { ERROR_CODES } from "../../../errors/error-codes.js";
import { ERROR_DEFINITIONS } from "../../../errors/error-definitions.js";
import { AppRequest } from "../../../types/request.js";
import { errorResponse, successResponse } from "../../../types/response.js";
import { ragService } from "../service/features.service.js";

const AI_SERVICE_URL = (
  process.env.AI_SERVICE_URL || "http://localhost:8000"
).replace(/\/+$/, "");
const USE_AI_MOCKS = process.env.AI_SERVICE_USE_MOCKS !== "false";

const MAX_UPLOAD_SIZE_BYTES = 10 * 1024 * 1024;
const DEFAULT_TIMEOUT_MS = 20_000;
const LONG_TIMEOUT_MS = 60_000;
const DEFAULT_PENDING_LIMIT = 100;
const DEFAULT_SENTIMENT_BATCH_SIZE = 100;
const DEFAULT_TOP_K = 5;
const MAX_TOP_K = 20;
const MAX_QUERY_LENGTH = 2000;

const ALLOWED_FILE_EXTENSIONS = new Set([".csv", ".xlsx", ".xlsm", ".pdf"]);

type JsonObject = Record<string, any>;
type ErrorCode = (typeof ERROR_CODES)[keyof typeof ERROR_CODES];

type UsageState = Awaited<ReturnType<typeof getRemainingUsage>>;

type AiServiceError = Error & {
  name: "AiServiceError";
  upstreamStatus?: number;
  kind: "external" | "llm";
};

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

function isAiServiceError(error: unknown): error is AiServiceError {
  return (
    error instanceof Error &&
    error.name === "AiServiceError" &&
    "kind" in error &&
    (error.kind === "external" || error.kind === "llm")
  );
}

function sendError(res: ExpressResponse, code: ErrorCode, detail?: any): void {
  const errDef = ERROR_DEFINITIONS[code];
  res
    .status(errDef.statusCode)
    .json(errorResponse(errDef.message, errDef.statusCode, code, detail));
}

function logControllerError(scope: string, error: unknown): void {
  if (error instanceof Error) {
    console.error(`[${scope}]`, {
      name: error.name,
      message: error.message,
      stack: error.stack
    });
    return;
  }

  console.error(`[${scope}]`, error);
}

function handleControllerError(
  res: ExpressResponse,
  scope: string,
  error: unknown
): void {
  logControllerError(scope, error);

  if (isAiServiceError(error)) {
    const code =
      error.kind === "llm"
        ? ERROR_CODES.UPSTREAM_LLM_FAILURE
        : ERROR_CODES.EXTERNAL_SERVICE_ERROR;

    sendError(res, code, {
      message: error.message,
      upstream_status: error.upstreamStatus ?? null
    });
    return;
  }

  sendError(res, ERROR_CODES.INTERNAL_SERVER_ERROR);
}

function getTenantId(req: AppRequest, res: ExpressResponse): string | null {
  const tenantId = req.tenant_id;

  if (typeof tenantId !== "string" || tenantId.trim().length === 0) {
    sendError(
      res,
      ERROR_CODES.FORBIDDEN,
      "Tenant context is required for this operation."
    );
    return null;
  }

  return tenantId;
}

function getAuthenticatedUserId(
  req: AppRequest,
  res: ExpressResponse
): string | null {
  const userId = req.user?.id;

  if (typeof userId !== "string" || userId.trim().length === 0) {
    sendError(
      res,
      ERROR_CODES.FORBIDDEN,
      "Authenticated user context is required for this operation."
    );
    return null;
  }

  return userId;
}

function getSingleString(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const normalized = value.trim();
  return normalized.length > 0 ? normalized : null;
}

function parseInteger(
  value: unknown,
  fallback: number,
  min: number,
  max: number
): number | null {
  if (value === undefined || value === null || value === "") return fallback;
  if (Array.isArray(value) || typeof value === "object") return null;

  const parsed = Number(value);
  if (!Number.isInteger(parsed) || parsed < min || parsed > max) return null;

  return parsed;
}

function getFileExtension(fileName: string): string {
  const normalized = fileName.toLowerCase();
  for (const extension of ALLOWED_FILE_EXTENSIONS) {
    if (normalized.endsWith(extension)) return extension;
  }
  return "";
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

function forwardedAuthHeaders(req: AppRequest): Record<string, string> {
  const authorization = req.headers.authorization;
  return authorization ? { Authorization: authorization } : {};
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

async function requireAvailableUsage(
  tenantId: string,
  featureCode: string,
  res: ExpressResponse,
  unavailableMessage: string,
  exhaustedMessage: string
): Promise<UsageState | null> {
  const usage = await getRemainingUsage(tenantId, featureCode);

  if (!usage) {
    sendError(res, ERROR_CODES.FORBIDDEN, unavailableMessage);
    return null;
  }

  const noRemainingQuota =
    usage.remaining !== null && Number(usage.remaining) <= 0;

  if (usage.isExceeded || noRemainingQuota) {
    sendError(res, ERROR_CODES.PAYMENT_REQUIRED, {
      message: exhaustedMessage,
      current_usage: usage.currentUsage,
      limit: usage.limit,
      remaining: 0
    });
    return null;
  }

  return usage;
}

function extractTotalTokens(data: JsonObject): number {
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

export const extractionController = {
  uploadFile: async (req: AppRequest, res: ExpressResponse): Promise<void> => {
    try {
      const tenantId = getTenantId(req, res);
      if (!tenantId) return;

      const userId = getAuthenticatedUserId(req, res);
      if (!userId) return;

      const file = req.file;
      if (!file) {
        sendError(
          res,
          ERROR_CODES.INVALID_FILE_UPLOAD,
          "A multipart file upload is required."
        );
        return;
      }

      const extension = getFileExtension(file.originalname);
      if (!extension) {
        sendError(
          res,
          ERROR_CODES.INVALID_FILE_UPLOAD,
          "Allowed file extensions are .csv, .xlsx, .xlsm, and .pdf."
        );
        return;
      }

      if (!Number.isFinite(file.size) || file.size <= 0) {
        sendError(
          res,
          ERROR_CODES.INVALID_FILE_UPLOAD,
          "The uploaded file is empty or has an invalid size."
        );
        return;
      }

      if (file.size > MAX_UPLOAD_SIZE_BYTES) {
        sendError(
          res,
          ERROR_CODES.FILE_SIZE_LIMIT_EXCEEDED,
          "File exceeds the 10 MB size limit."
        );
        return;
      }

      const mbUsed = Math.max(1, Math.ceil(file.size / (1024 * 1024)));
      const usage = await requireAvailableUsage(
        tenantId,
        "document_extraction",
        res,
        "Document extraction is not available for this subscription.",
        "Document extraction quota has been reached."
      );
      if (!usage) return;

      if (usage.remaining !== null && mbUsed > Number(usage.remaining)) {
        sendError(res, ERROR_CODES.PAYMENT_REQUIRED, {
          message:
            "This upload exceeds the remaining document extraction quota.",
          requested: mbUsed,
          remaining: usage.remaining,
          unit: "MB"
        });
        return;
      }

      const fileName = safeUploadName(file.originalname);
      let data: JsonObject;

      if (USE_AI_MOCKS) {
        data = mockExtractionData(tenantId, fileName);
      } else {
        const formData = new FormData();
        formData.append(
          "file",
          new Blob([new Uint8Array(file.buffer)], { type: file.mimetype }),
          fileName
        );

        data = await requestAiJson(
          aiUrl("extraction/upload"),
          {
            method: "POST",
            headers: forwardedAuthHeaders(req),
            body: formData
          },
          {
            timeoutMs: LONG_TIMEOUT_MS,
            serviceName: "AI extraction service"
          }
        );
      }

      const minioObjectKey = getSingleString(data.minio_object_key);
      if (!minioObjectKey) {
        throw createAiServiceError(
          "AI extraction service response is missing minio_object_key."
        );
      }

      await documentsRepo.insertRagDocumentMeta({
        userId,
        fileSize: BigInt(file.size),
        minio_object_key: minioObjectKey,
        tenantId,
        filename: file.originalname,
        mimetype: file.mimetype
      });

      await incrementUsage(tenantId, "document_extraction", mbUsed);

      res.status(200).json(
        successResponse(
          {
            job_id: data.job_id,
            template_mode: data.template_mode,
            is_template_compliant: data.is_template_compliant,
            rows_processed: data.rows_processed,
            rows_partial: data.rows_partial,
            rows_failed: data.rows_failed,
            data_loss_pct: data.data_loss_pct,
            header_coverage_ratio: data.header_coverage_ratio,
            row_outcomes: data.row_outcomes,
            promotion: data.promotion,
            currency_resolution: data.currency_resolution
          },
          "Document extraction successful"
        )
      );
    } catch (error) {
      handleControllerError(res, "ExtractionController.uploadFile", error);
    }
  },

  processPending: async (
    req: AppRequest,
    res: ExpressResponse
  ): Promise<void> => {
    try {
      const tenantId = getTenantId(req, res);
      if (!tenantId) return;

      const requestedLimit = parseInteger(
        req.query.limit,
        DEFAULT_PENDING_LIMIT,
        1,
        1000
      );
      if (requestedLimit === null) {
        sendError(
          res,
          ERROR_CODES.INVALID_PARAMETER,
          "limit must be an integer between 1 and 1000."
        );
        return;
      }

      const usage = await requireAvailableUsage(
        tenantId,
        "document_extraction",
        res,
        "Document extraction is not available for this subscription.",
        "Document extraction quota has been reached."
      );
      if (!usage) return;

      const allowedLimit =
        usage.remaining === null
          ? requestedLimit
          : Math.max(0, Math.min(requestedLimit, Number(usage.remaining)));

      // This endpoint currently has no documented downstream processing call.
      // Return the quota-safe limit rather than silently calculating and ignoring it.
      res.status(200).json(
        successResponse(
          {
            message: "Pending extraction request accepted",
            requested_limit: requestedLimit,
            allowed_limit: allowedLimit
          },
          "Process pending request accepted"
        )
      );
    } catch (error) {
      handleControllerError(res, "ExtractionController.processPending", error);
    }
  }
};

export const ragController = {
  queryAssistant: async (
    req: AppRequest,
    res: ExpressResponse
  ): Promise<void> => {
    try {
      const tenantId = getTenantId(req, res);
      if (!tenantId) return;

      const queryText = getSingleString(req.query.query_text);
      if (!queryText) {
        sendError(
          res,
          ERROR_CODES.INVALID_REQUEST,
          "query_text is required as a non-empty string."
        );
        return;
      }

      if (queryText.length > MAX_QUERY_LENGTH) {
        sendError(
          res,
          ERROR_CODES.INVALID_PARAMETER,
          `query_text must not exceed ${MAX_QUERY_LENGTH} characters.`
        );
        return;
      }

      const topK = parseInteger(req.query.top_k, DEFAULT_TOP_K, 1, MAX_TOP_K);
      if (topK === null) {
        sendError(
          res,
          ERROR_CODES.INVALID_PARAMETER,
          `top_k must be an integer between 1 and ${MAX_TOP_K}.`
        );
        return;
      }

      let historyJson: string | undefined;
      if (req.query.history_json !== undefined) {
        if (typeof req.query.history_json !== "string") {
          sendError(
            res,
            ERROR_CODES.MALFORMED_HISTORY_JSON,
            "history_json must be a JSON array string."
          );
          return;
        }

        try {
          const parsedHistory = JSON.parse(req.query.history_json);
          if (!Array.isArray(parsedHistory)) {
            throw new Error("history_json must decode to an array.");
          }
          historyJson = JSON.stringify(parsedHistory);
        } catch {
          sendError(
            res,
            ERROR_CODES.MALFORMED_HISTORY_JSON,
            "history_json must be a valid JSON array string."
          );
          return;
        }
      }

      const usage = await requireAvailableUsage(
        tenantId,
        "rag_assistant",
        res,
        "RAG assistant is not available for this subscription.",
        "RAG token quota has been reached."
      );
      if (!usage) return;

      let data: JsonObject;
      if (USE_AI_MOCKS) {
        data = MOCK_RAG_RESPONSE;
      } else {
        const url = aiUrl("rag/query");
        url.searchParams.set("query_text", queryText);
        url.searchParams.set("top_k", String(topK));
        if (historyJson) url.searchParams.set("history_json", historyJson);

        data = await requestAiJson(
          url,
          {
            method: "POST",
            headers: forwardedAuthHeaders(req)
          },
          {
            timeoutMs: LONG_TIMEOUT_MS,
            serviceName: "RAG AI service",
            mapServerErrorsToLlmFailure: true
          }
        );
      }

      const totalTokens = extractTotalTokens(data);
      if (totalTokens > 0) {
        // Charge actual model consumption (input + output tokens when available).
        // Exact token usage is only known after the model responds, so a single
        // request may cross the final remaining-token boundary. The next request
        // will then be blocked by requireAvailableUsage().
        await incrementUsage(tenantId, "rag_assistant", totalTokens);
      }

      res.status(200).json(
        successResponse(
          {
            answer: data.answer,
            sources: Array.isArray(data.sources) ? data.sources : []
          },
          "Assistant query successful"
        )
      );
    } catch (error) {
      handleControllerError(res, "RagController.queryAssistant", error);
    }
  },

  getChunk: async (req: AppRequest, res: ExpressResponse): Promise<void> => {
    try {
      const tenantId = getTenantId(req, res);
      if (!tenantId) return;

      const chunkId = getSingleString(req.params.chunk_id);
      if (!chunkId) {
        sendError(
          res,
          ERROR_CODES.INVALID_REQUEST,
          "chunk_id path parameter is required."
        );
        return;
      }

      let chunkData: JsonObject | null = null;

      if (USE_AI_MOCKS) {
        chunkData = MOCK_RAG_CHUNKS[chunkId] ?? null;
      } else {
        try {
          chunkData = (await ragService.fetchChunkDetails(
            tenantId,
            chunkId
          )) as JsonObject;
        } catch (error: any) {
          if (error?.code === "NOT_FOUND") {
            sendError(
              res,
              ERROR_CODES.RESOURCE_NOT_FOUND,
              error?.message ?? `Chunk ${chunkId} was not found.`
            );
            return;
          }
          throw error;
        }
      }

      if (!chunkData) {
        sendError(
          res,
          ERROR_CODES.RESOURCE_NOT_FOUND,
          `Chunk ${chunkId} was not found.`
        );
        return;
      }

      res
        .status(200)
        .json(successResponse(chunkData, "Chunk fetched successfully"));
    } catch (error) {
      handleControllerError(res, "RagController.getChunk", error);
    }
  }
};

export const pricingController = {
  getRecommendation: async (
    req: AppRequest,
    res: ExpressResponse
  ): Promise<void> => {
    try {
      const tenantId = getTenantId(req, res);
      if (!tenantId) return;

      const productId = getSingleString(req.query.product_id);
      if (!productId) {
        sendError(
          res,
          ERROR_CODES.INVALID_REQUEST,
          "product_id query parameter is required as a string."
        );
        return;
      }

      const usage = await requireAvailableUsage(
        tenantId,
        "ai_pricing",
        res,
        "AI pricing is not available for this subscription.",
        "AI pricing quota has been reached."
      );
      if (!usage) return;

      const url = aiUrl("pricing/recommend");
      url.searchParams.set("product_id", productId);

      const data = await requestAiJson(
        url,
        {
          method: "POST",
          headers: forwardedAuthHeaders(req)
        },
        {
          serviceName: "AI pricing service"
        }
      );

      await incrementUsage(tenantId, "ai_pricing");

      res.status(200).json(
        successResponse(
          {
            status: data.status,
            action: data.action,
            current_price: data.current_price,
            suggested_price: data.suggested_price,
            clamped: data.clamped,
            max_change_pct: data.max_change_pct,
            min_margin_pct: data.min_margin_pct,
            floor_price: data.floor_price,
            market_min: data.market_min,
            market_max: data.market_max,
            market_avg: data.market_avg,
            market_median: data.market_median,
            matched_competitor_count: data.matched_competitor_count,
            confidence_score: data.confidence_score,
            explanation: data.explanation,
            evidence_id: data.evidence_id
          },
          "Pricing recommendation fetched successfully"
        )
      );
    } catch (error) {
      handleControllerError(res, "PricingController.getRecommendation", error);
    }
  }
};

export const sentimentController = {
  analyzePending: async (
    req: AppRequest,
    res: ExpressResponse
  ): Promise<void> => {
    try {
      const tenantId = getTenantId(req, res);
      if (!tenantId) return;

      const requestedBatchSize = parseInteger(
        req.query.batch_size,
        DEFAULT_SENTIMENT_BATCH_SIZE,
        1,
        1000
      );
      if (requestedBatchSize === null) {
        sendError(
          res,
          ERROR_CODES.INVALID_PARAMETER,
          "batch_size must be an integer between 1 and 1000."
        );
        return;
      }

      const usage = await requireAvailableUsage(
        tenantId,
        "sentiment_analysis",
        res,
        "Sentiment analysis is not available for this subscription.",
        "Sentiment analysis quota has been reached."
      );
      if (!usage) return;

      const allowedBatchSize =
        usage.remaining === null
          ? requestedBatchSize
          : Math.max(0, Math.min(requestedBatchSize, Number(usage.remaining)));

      if (allowedBatchSize <= 0) {
        sendError(res, ERROR_CODES.PAYMENT_REQUIRED, {
          message: "Sentiment analysis quota has been reached.",
          current_usage: usage.currentUsage,
          limit: usage.limit,
          remaining: 0
        });
        return;
      }

      const url = aiUrl("sentiment/analyze-pending");
      url.searchParams.set("batch_size", String(allowedBatchSize));

      const data = await requestAiJson(
        url,
        {
          method: "POST",
          headers: forwardedAuthHeaders(req)
        },
        {
          timeoutMs: LONG_TIMEOUT_MS,
          serviceName: "AI sentiment service"
        }
      );

      const analyzedCount = Number(data.analyzed_count ?? 0);
      if (!Number.isFinite(analyzedCount) || analyzedCount < 0) {
        throw createAiServiceError(
          "AI sentiment service returned an invalid analyzed_count."
        );
      }

      const safeAnalyzedCount = Math.floor(analyzedCount);
      if (safeAnalyzedCount > allowedBatchSize) {
        throw createAiServiceError(
          "AI sentiment service processed more records than the allowed batch size."
        );
      }

      if (safeAnalyzedCount > 0) {
        await incrementUsage(tenantId, "sentiment_analysis", safeAnalyzedCount);
      }

      res.status(200).json(
        successResponse(
          {
            status: data.status,
            analyzed_count: safeAnalyzedCount,
            requested_batch_size: requestedBatchSize,
            allowed_batch_size: allowedBatchSize
          },
          "Batch sentiment analysis completed"
        )
      );
    } catch (error) {
      handleControllerError(res, "SentimentController.analyzePending", error);
    }
  },

  getSummary: async (req: AppRequest, res: ExpressResponse): Promise<void> => {
    try {
      const tenantId = getTenantId(req, res);
      if (!tenantId) return;

      const subjectType = getSingleString(req.query.subject_type);
      const subjectId = getSingleString(req.query.subject_id);
      if (!subjectType || !subjectId) {
        sendError(
          res,
          ERROR_CODES.INVALID_REQUEST,
          "subject_type and subject_id are required as strings."
        );
        return;
      }

      const url = aiUrl("sentiment/summary");
      url.searchParams.set("subject_type", subjectType);
      url.searchParams.set("subject_id", subjectId);

      const data = await requestAiJson(
        url,
        {
          method: "GET",
          headers: forwardedAuthHeaders(req)
        },
        {
          serviceName: "AI sentiment service"
        }
      );

      res.status(200).json(
        successResponse(
          {
            status: data.status,
            sentiment_score: data.sentiment_score,
            label_counts: data.label_counts,
            sample_size: data.sample_size,
            evidence_id: data.evidence_id
          },
          "Sentiment summary retrieved successfully"
        )
      );
    } catch (error) {
      handleControllerError(res, "SentimentController.getSummary", error);
    }
  }
};

export const mpiController = {
  getSummary: async (req: AppRequest, res: ExpressResponse): Promise<void> => {
    try {
      const tenantId = getTenantId(req, res);
      if (!tenantId) return;

      const subjectType = getSingleString(req.query.subject_type);
      const subjectId = getSingleString(req.query.subject_id);
      if (!subjectType || !subjectId) {
        sendError(
          res,
          ERROR_CODES.INVALID_REQUEST,
          "subject_type and subject_id are required as strings."
        );
        return;
      }

      const url = aiUrl("mpi/summary");
      url.searchParams.set("subject_type", subjectType);
      url.searchParams.set("subject_id", subjectId);

      const data = await requestAiJson(
        url,
        {
          method: "GET",
          headers: forwardedAuthHeaders(req)
        },
        {
          serviceName: "AI MPI service"
        }
      );

      res.status(200).json(
        successResponse(
          {
            status: data.status,
            mpi: data.mpi,
            weighted_sentiment_score: data.weighted_sentiment_score,
            volume_confidence: data.volume_confidence,
            review_count: data.review_count,
            avg_recency_weight: data.avg_recency_weight,
            avg_reliability_weight: data.avg_reliability_weight,
            label_counts: data.label_counts,
            confidence_score: data.confidence_score,
            sample_size: data.sample_size,
            evidence_id: data.evidence_id
          },
          "Market Perception Index fetched successfully"
        )
      );
    } catch (error) {
      handleControllerError(res, "MpiController.getSummary", error);
    }
  }
};

export const documentController = {
  listDocuments: async (
    req: AppRequest,
    res: ExpressResponse
  ): Promise<void> => {
    try {
      const tenantId = getTenantId(req, res);
      if (!tenantId) return;

      const page = parseInteger(req.query.page, 1, 1, 1_000_000);
      if (page === null) {
        sendError(
          res,
          ERROR_CODES.INVALID_PARAMETER,
          "page must be a positive integer."
        );
        return;
      }

      const pageSize = 10;
      const [documents, total] = await Promise.all([
        documentsRepo.getDocuments({
          tenant_id: tenantId,
          page,
          pageSize
        }),
        documentsRepo.getCountDocuments(tenantId)
      ]);

      const formattedDocuments = documents.map((doc) => ({
        ...doc,
        file_size_bytes:
          doc.file_size_bytes === null || doc.file_size_bytes === undefined
            ? null
            : doc.file_size_bytes.toString()
      }));

      res.status(200).json(
        successResponse(
          {
            documents: formattedDocuments,
            pagination: {
              page,
              pageSize,
              total,
              totalPages: Math.ceil(total / pageSize)
            }
          },
          "Documents fetched successfully"
        )
      );
    } catch (error) {
      handleControllerError(res, "DocumentController.listDocuments", error);
    }
  }
};
