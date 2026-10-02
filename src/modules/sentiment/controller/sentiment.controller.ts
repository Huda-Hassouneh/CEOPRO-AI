import type { NextFunction, Response } from "express";
import { ERROR_CODES } from "../../../errors/error-codes.js";
import type { AppRequest } from "../../../types/request.js";
import { successResponse } from "../../../types/response.js";
import { sendApiError } from "../../../utils/http.js";
import { isSentimentClientError } from "../client/sentiment.client.js";
import {
  analyzePendingSentiment,
  getSentimentSummary,
  isSentimentServiceError
} from "../service/sentiment.service.js";
import type { SentimentSubjectType } from "../types/sentiment.types.js";

export async function analyzePending(
  req: AppRequest,
  res: Response,
  next: NextFunction
): Promise<void> {
  try {
    const tenantId = req.tenant_id;
    const authorization = req.headers.authorization;
    const requestedBatchSize =
      typeof req.query.batch_size === "number"
        ? req.query.batch_size
        : undefined;

    if (!tenantId) {
      sendApiError(res, ERROR_CODES.TENANT_ACCESS_DENIED);
      return;
    }

    if (!authorization) {
      sendApiError(res, ERROR_CODES.INVALID_AUTH_HEADER);
      return;
    }

    const data = await analyzePendingSentiment({
      tenantId,
      requestedBatchSize,
      authorization
    });

    res
      .status(200)
      .json(successResponse(data, "Batch sentiment analysis completed"));
  } catch (error) {
    if (isSentimentServiceError(error)) {
      if (error.code === "ENTITLEMENT_NOT_AVAILABLE") {
        sendApiError(res, ERROR_CODES.FORBIDDEN, {
          publicMessage: error.message
        });
        return;
      }

      if (error.code === "QUOTA_EXCEEDED") {
        sendApiError(res, ERROR_CODES.PAYMENT_REQUIRED, {
          publicMessage: error.message,
          details: error.details
        });
        return;
      }

      if (error.code === "AI_PROCESSED_OVER_LIMIT") {
        sendApiError(res, ERROR_CODES.EXTERNAL_SERVICE_ERROR, {
          details: {
            service: "AI sentiment service",
            reason: error.message,
            ...(typeof error.details === "object" && error.details !== null
              ? error.details
              : {})
          }
        });
        return;
      }
    }

    if (isSentimentClientError(error)) {
      sendApiError(res, ERROR_CODES.EXTERNAL_SERVICE_ERROR, {
        details: {
          service: "AI sentiment service",
          upstream_status: error.upstreamStatus ?? null
        }
      });
      return;
    }

    next(error);
  }
}

export async function getSummary(
  req: AppRequest,
  res: Response,
  next: NextFunction
): Promise<void> {
  try {
    const tenantId = req.tenant_id;
    const authorization = req.headers.authorization;
    const subjectType = req.query.subject_type as SentimentSubjectType;
    const subjectId =
      typeof req.query.subject_id === "string"
        ? req.query.subject_id
        : undefined;
    const countryContext =
      typeof req.query.country_context === "string"
        ? req.query.country_context
        : undefined;

    if (!tenantId) {
      sendApiError(res, ERROR_CODES.TENANT_ACCESS_DENIED);
      return;
    }

    if (!authorization) {
      sendApiError(res, ERROR_CODES.INVALID_AUTH_HEADER);
      return;
    }

    const data = await getSentimentSummary({
      subjectType,
      subjectId,
      countryContext,
      authorization
    });

    res
      .status(200)
      .json(successResponse(data, "Sentiment summary retrieved successfully"));
  } catch (error) {
    if (isSentimentClientError(error)) {
      sendApiError(res, ERROR_CODES.EXTERNAL_SERVICE_ERROR, {
        details: {
          service: "AI sentiment service",
          upstream_status: error.upstreamStatus ?? null
        }
      });
      return;
    }

    next(error);
  }
}
