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
    const userId = req.user?.user_id;
    const subjectType = req.query.subject_type as MpiSubjectType;
    const subjectId =
      typeof req.query.subject_id === "string"
        ? req.query.subject_id
        : undefined;

    if (!tenantId || !userId) {
      sendApiError(res, ERROR_CODES.TENANT_ACCESS_DENIED);
      return;
    }

    const data = await getMpiSummary({
      tenantId,
      userId,
      subjectType,
      subjectId
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
