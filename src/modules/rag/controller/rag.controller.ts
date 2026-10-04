import type { Response as ExpressResponse } from "express";
import { ERROR_CODES } from "../../../errors/error-codes.js";
import { ERROR_DEFINITIONS } from "../../../errors/error-definitions.js";
import type { AppRequest } from "../../../types/request.js";
import { errorResponse, successResponse } from "../../../types/response.js";
import { isRagClientError } from "../client/rag.client.js";
import {
  getRagChunkDetail,
  getRagDocuments,
  isRagServiceError,
  queryRag,
  uploadRagDocument
} from "../service/rag.service.js";

type ErrorCode = (typeof ERROR_CODES)[keyof typeof ERROR_CODES];

function sendError(
  res: ExpressResponse,
  code: ErrorCode,
  detail?: unknown
): void {
  const definition = ERROR_DEFINITIONS[code];
  res
    .status(definition.statusCode)
    .json(
      errorResponse(
        definition.message,
        definition.statusCode,
        code,
        detail
      )
    );
}

function handleError(res: ExpressResponse, error: unknown): void {
  console.error("[RagController]", error);

  if (isRagServiceError(error)) {
    switch (error.code) {
      case "INVALID_FILE_UPLOAD":
        sendError(
          res,
          ERROR_CODES.INVALID_FILE_UPLOAD,
          error.detail ?? error.message
        );
        return;
      case "FILE_SIZE_LIMIT_EXCEEDED":
        sendError(
          res,
          ERROR_CODES.FILE_SIZE_LIMIT_EXCEEDED,
          error.detail ?? error.message
        );
        return;
      case "FEATURE_NOT_INCLUDED":
        sendError(res, ERROR_CODES.FORBIDDEN, error.detail ?? error.message);
        return;
      case "USAGE_EXCEEDED":
      case "STORAGE_EXCEEDED":
        sendError(
          res,
          ERROR_CODES.PAYMENT_REQUIRED,
          error.detail ?? { message: error.message }
        );
        return;
      case "MALFORMED_HISTORY_JSON":
        sendError(
          res,
          ERROR_CODES.MALFORMED_HISTORY_JSON,
          error.detail ?? error.message
        );
        return;
      case "NOT_FOUND":
        sendError(
          res,
          ERROR_CODES.RESOURCE_NOT_FOUND,
          error.detail ?? error.message
        );
        return;
    }
  }

  if (isRagClientError(error)) {
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
  if (typeof tenantId !== "string" || !tenantId.trim()) {
    sendError(
      res,
      ERROR_CODES.FORBIDDEN,
      "Tenant context is required for this operation."
    );
    return null;
  }
  return tenantId;
}

function getUserId(req: AppRequest, res: ExpressResponse): string | null {
  const userId = req.user?.id;
  if (typeof userId !== "string" || !userId.trim()) {
    sendError(
      res,
      ERROR_CODES.FORBIDDEN,
      "Authenticated user context is required for this operation."
    );
    return null;
  }
  return userId;
}

export const ragController = {
  listDocuments: async (
    req: AppRequest,
    res: ExpressResponse
  ): Promise<void> => {
    try {
      const tenantId = getTenantId(req, res);
      if (!tenantId) return;

      const page = Number(req.query.page ?? 1);
      const data = await getRagDocuments({ tenantId, page });

      res
        .status(200)
        .json(successResponse(data, "Documents fetched successfully"));
    } catch (error) {
      handleError(res, error);
    }
  },

  uploadDocument: async (
    req: AppRequest,
    res: ExpressResponse
  ): Promise<void> => {
    try {
      const tenantId = getTenantId(req, res);
      if (!tenantId) return;

      const userId = getUserId(req, res);
      if (!userId) return;

      if (!req.file) {
        sendError(
          res,
          ERROR_CODES.INVALID_FILE_UPLOAD,
          "A multipart file upload is required in field 'file'."
        );
        return;
      }

      const data = await uploadRagDocument({
        tenantId,
        userId,
        authorization: req.headers.authorization,
        file: {
          originalname: req.file.originalname,
          mimetype: req.file.mimetype,
          size: req.file.size,
          buffer: req.file.buffer
        }
      });

      res
        .status(201)
        .json(successResponse(data, "RAG document upload accepted"));
    } catch (error) {
      handleError(res, error);
    }
  },

  queryAssistant: async (
    req: AppRequest,
    res: ExpressResponse
  ): Promise<void> => {
    try {
      const tenantId = getTenantId(req, res);
      if (!tenantId) return;

      const data = await queryRag({
        tenantId,
        queryText: String(req.query.query_text),
        topK: Number(req.query.top_k ?? 5),
        historyJson:
          typeof req.query.history_json === "string"
            ? req.query.history_json
            : undefined,
        authorization: req.headers.authorization
      });

      res
        .status(200)
        .json(successResponse(data, "Assistant query successful"));
    } catch (error) {
      handleError(res, error);
    }
  },

  getChunk: async (req: AppRequest, res: ExpressResponse): Promise<void> => {
    try {
      const tenantId = getTenantId(req, res);
      if (!tenantId) return;

      const chunkId = String(req.params.chunk_id || "").trim();
      if (!chunkId) {
        sendError(
          res,
          ERROR_CODES.INVALID_REQUEST,
          "chunk_id path parameter is required."
        );
        return;
      }

      const data = await getRagChunkDetail(tenantId, chunkId);
      res
        .status(200)
        .json(successResponse(data, "Chunk fetched successfully"));
    } catch (error) {
      handleError(res, error);
    }
  }
};
