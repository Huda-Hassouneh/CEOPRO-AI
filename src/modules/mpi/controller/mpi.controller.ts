import type { NextFunction, Response } from "express";
import { ERROR_CODES } from "../../../errors/error-codes.js";
import type { AppRequest } from "../../../types/request.js";
import { successResponse } from "../../../types/response.js";
import { sendApiError } from "../../../utils/http.js";
import { isMpiClientError } from "../client/mpi.client.js";
import { getMpiSummary } from "../service/mpi.service.js";
import type { MpiSubjectType } from "../types/mpi.types.js";

export async function getSummary(
  req: AppRequest,
  res: Response,
  next: NextFunction
): Promise<void> {
  try {
    const tenantId = req.tenant_id;
    const authorization = req.headers.authorization;
    const subjectType = req.query.subject_type as MpiSubjectType;
    const subjectId =
      typeof req.query.subject_id === "string"
        ? req.query.subject_id
        : undefined;

    if (!tenantId) {
      sendApiError(res, ERROR_CODES.TENANT_ACCESS_DENIED);
      return;
    }

    if (!authorization) {
      sendApiError(res, ERROR_CODES.INVALID_AUTH_HEADER);
      return;
    }

    const data = await getMpiSummary({
      subjectType,
      subjectId,
      authorization
    });

    res
      .status(200)
      .json(successResponse(data, "Market Perception Index fetched successfully"));
  } catch (error) {
    if (isMpiClientError(error)) {
      sendApiError(res, ERROR_CODES.EXTERNAL_SERVICE_ERROR, {
        details: {
          service: "AI MPI service",
          upstream_status: error.upstreamStatus ?? null
        }
      });
      return;
    }

    next(error);
  }
}
