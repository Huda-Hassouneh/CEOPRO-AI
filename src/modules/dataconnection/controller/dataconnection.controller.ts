import { Response as ExpressResponse, NextFunction, Response } from "express";

import { ERROR_CODES } from "../../../errors/error-codes.js";
import { ERROR_DEFINITIONS } from "../../../errors/error-definitions.js";
import { AppRequest } from "../../../types/request.js";
import { errorResponse, successResponse } from "../../../types/response.js";

import {
  isDataConnectionServiceError,
  dataConnectionService
} from "../service/dataconnection.service.js";

import { isAiServiceError } from "../client/ingestion.client.js";

type ErrorCode = (typeof ERROR_CODES)[keyof typeof ERROR_CODES];

function sendError(res: ExpressResponse, code: ErrorCode, detail?: any): void {
  const errDef = ERROR_DEFINITIONS[code];

  res
    .status(errDef.statusCode)
    .json(errorResponse(errDef.message, errDef.statusCode, code, detail));
}

function parseInteger(
  value: unknown,
  fallback: number,
  min: number,
  max: number
): number | null {
  if (value === undefined || value === null || value === "") {
    return fallback;
  }

  if (Array.isArray(value) || typeof value === "object") {
    return null;
  }

  const parsed = Number(value);

  if (!Number.isInteger(parsed) || parsed < min || parsed > max) {
    return null;
  }

  return parsed;
}

function handleError(res: ExpressResponse, error: unknown): void {
  console.error("[DataConnectionController]", error);

  if (isDataConnectionServiceError(error)) {
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
          error.detail ?? {
            message: error.message
          }
        );
        return;
    }
  }

  if (isAiServiceError(error)) {
    sendError(res, ERROR_CODES.EXTERNAL_SERVICE_ERROR, {
      message: error.message,
      upstream_status: error.upstreamStatus ?? null
    });
    return;
  }

  sendError(res, ERROR_CODES.INTERNAL_SERVER_ERROR);
}

export const dataConnectionController = {
  uploadFile: async (req: AppRequest, res: ExpressResponse): Promise<void> => {
    try {
      const tenantId = req.tenant_id;
      console.log({ tenantId });

      const userId = req.user?.id;

      if (typeof tenantId !== "string" || !tenantId.trim()) {
        sendError(
          res,
          ERROR_CODES.FORBIDDEN,
          "Tenant context is required for this operation."
        );
        return;
      }

      if (typeof userId !== "string" || !userId.trim()) {
        sendError(
          res,
          ERROR_CODES.FORBIDDEN,
          "Authenticated user context is required for this operation."
        );
        return;
      }

      if (!req.file) {
        sendError(
          res,
          ERROR_CODES.INVALID_FILE_UPLOAD,
          "A multipart file upload is required."
        );
        return;
      }

      const result = await dataConnectionService.uploadExtraction({
        tenantId,
        userId,
        file: req.file,
        authorization: req.headers.authorization
      });

      res
        .status(200)
        .json(successResponse(result, "Document extraction successful"));
    } catch (error) {
      handleError(res, error);
    }
  },

  processPending: async (
    req: AppRequest,
    res: ExpressResponse
  ): Promise<void> => {
    try {
      const tenantId = req.tenant_id;

      if (typeof tenantId !== "string" || !tenantId.trim()) {
        sendError(
          res,
          ERROR_CODES.FORBIDDEN,
          "Tenant context is required for this operation."
        );
        return;
      }

      const requestedLimit = parseInteger(req.query.limit, 100, 1, 1000);

      if (requestedLimit === null) {
        sendError(
          res,
          ERROR_CODES.INVALID_PARAMETER,
          "limit must be an integer between 1 and 1000."
        );
        return;
      }

      const result = await dataConnectionService.processPending({
        tenantId,
        requestedLimit,
        authorization: req.headers.authorization
      });

      res
        .status(200)
        .json(successResponse(result, "Pending extraction completed"));
    } catch (error) {
      handleError(res, error);
    }
  },
  getConnectionsOverview: async (
    req: any,
    res: Response,
    next: NextFunction
  ) => {
    try {
      const tenantId = req.tenant_id;

      const data =
        await dataConnectionService.getDataConnectionsOverview(tenantId);

      return res.status(200).json({
        status: "success",
        data
      });
    } catch (error) {
      next(error);
    }
  },

  createSource: async (
    req: AppRequest,
    res: ExpressResponse
  ): Promise<void> => {
    try {
      const tenantId = req.tenant_id;

      if (typeof tenantId !== "string" || tenantId.trim().length === 0) {
        sendError(res, ERROR_CODES.FORBIDDEN, "Tenant context is required.");
        return;
      }

      const source = await dataConnectionService.createDataSource({
        tenantId,
        payload: req.body
      });

      res
        .status(201)
        .json(successResponse(source, "Data source created successfully"));
    } catch (error) {
      handleError(res, error);
    }
  }
};
