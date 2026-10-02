import type { NextFunction, Response } from "express";
import { z } from "zod";
import { ERROR_CODES } from "../../../errors/error-codes.js";
import type { AppRequest } from "../../../types/request.js";
import { sendApiError } from "../../../utils/http.js";

export const mpiSummaryQuerySchema = z.object({
  subject_type: z.enum(["PRODUCT", "COMPETITOR", "BUSINESS"], {
    error: "subject_type must be one of 'PRODUCT', 'COMPETITOR', or 'BUSINESS'"
  }),
  subject_id: z
    .string()
    .uuid("subject_id must be a valid UUID")
    .optional()
});

function applyParsedQuery(
  req: AppRequest,
  parsed: Record<string, unknown>
): void {
  Object.defineProperty(req, "query", {
    value: parsed,
    writable: true,
    enumerable: true,
    configurable: true
  });
}

export function validateMpiSummaryQuery(
  req: AppRequest,
  res: Response,
  next: NextFunction
): void {
  const result = mpiSummaryQuerySchema.safeParse(req.query);

  if (!result.success) {
    sendApiError(res, ERROR_CODES.VALIDATION_ERROR, {
      details: result.error.issues.map((issue) => ({
        field: issue.path.join("."),
        message: issue.message
      }))
    });
    return;
  }

  applyParsedQuery(req, result.data);
  next();
}
