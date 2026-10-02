import { Response as ExpressResponse } from "express";
import {
  assertFeatureCapacity,
  documentsRepo,
  getRemainingUsage,
  incrementUsage
} from "../repo/usage.repo.js";
import { ERROR_CODES } from "../../../errors/error-codes.js";
import { ERROR_DEFINITIONS } from "../../../errors/error-definitions.js";
import { AppRequest } from "../../../types/request.js";
import { errorResponse, successResponse } from "../../../types/response.js";
import { ragService } from "../service/features.service.js";
import {
  getMockRagChunk,
  isAiServiceError,
  isFeaturesAiMockModeEnabled,
  queryRagAi,
  uploadExtractionFileToAi,
  type JsonObject
} from "../client/features-ai.client.js";
const MAX_UPLOAD_SIZE_BYTES = 10 * 1024 * 1024;
const DEFAULT_PENDING_LIMIT = 100;
const DEFAULT_TOP_K = 5;
const MAX_TOP_K = 20;
const MAX_QUERY_LENGTH = 2000;
const ALLOWED_FILE_EXTENSIONS = new Set([".csv", ".xlsx", ".xlsm", ".pdf"]);
type ErrorCode = (typeof ERROR_CODES)[keyof typeof ERROR_CODES];
type UsageState = Awaited<ReturnType<typeof getRemainingUsage>>;

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

      // -----------------------------------------------------
      // DOCUMENT EXTRACTION USAGE
      // Stored internally as whole KB.
      //
      // Example:
      // 340 KB file -> ~340 KB usage
      // 1.5 MB file -> ~1536 KB usage
      // -----------------------------------------------------
      const kbUsed = Math.max(1, Math.ceil(file.size / 1024));

      const usage = await requireAvailableUsage(
        tenantId,
        "document_extraction",
        res,
        "Document extraction is not available for this subscription.",
        "Document extraction quota has been reached."
      );

      if (!usage) return;

      if (usage.remaining !== null && kbUsed > Number(usage.remaining)) {
        sendError(res, ERROR_CODES.PAYMENT_REQUIRED, {
          message:
            "This upload exceeds the remaining document extraction quota.",
          requested: kbUsed,
          remaining: usage.remaining,
          unit: "KB"
        });
        return;
      }

      // -----------------------------------------------------
      // DOCUMENT STORAGE CAPACITY
      // document_storage_mb is measured in MB.
      // Keep fractional MB here because capacity usage is
      // derived from actual file bytes.
      // -----------------------------------------------------
      const storageMb = file.size / 1024 ** 2;

      const storage = await assertFeatureCapacity({
        tenantId,
        featureCode: "document_storage_mb",
        additionalAmount: storageMb
      });

      if (!storage.allowed) {
        if (storage.reason === "FEATURE_NOT_INCLUDED") {
          sendError(
            res,
            ERROR_CODES.FORBIDDEN,
            "Document storage is not available for this subscription."
          );
        } else {
          sendError(res, ERROR_CODES.PAYMENT_REQUIRED, {
            message:
              "This upload exceeds the available document storage capacity.",
            feature_code: "document_storage_mb",
            reason: "CAPACITY_REACHED",
            current_usage: storage.entitlement.currentUsage,
            limit: storage.entitlement.limit,
            requested: storageMb,
            remaining: storage.entitlement.remaining,
            unit: "MB"
          });
        }

        return;
      }

      const data = await uploadExtractionFileToAi({
        tenantId,
        file: {
          originalname: file.originalname,
          mimetype: file.mimetype,
          buffer: file.buffer
        },
        authorization: req.headers.authorization
      });

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

      // Extraction usage is now persisted in KB.
      await incrementUsage(tenantId, "document_extraction", kbUsed);

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
      const data = await queryRagAi({
        queryText,
        topK,
        historyJson,
        authorization: req.headers.authorization
      });
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
      if (isFeaturesAiMockModeEnabled()) {
        chunkData = getMockRagChunk(chunkId);
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
      const pageSize = 3;
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
console.log("AI mocks enabled:", isFeaturesAiMockModeEnabled());
