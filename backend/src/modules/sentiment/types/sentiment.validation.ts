import type { NextFunction, Response } from "express";
import { z } from "zod";
import { ERROR_CODES } from "../../../errors/error-codes.js";
import type { AppRequest } from "../../../types/request.js";
import { sendApiError } from "../../../utils/http.js";

export const sentimentAnalyzePendingQuerySchema = z.object({
  batch_size: z.coerce
    .number()
    .int("batch_size must be an integer")
    .positive("batch_size must be greater than 0")
    .max(1000, "batch_size cannot exceed 1000")
    .optional()
});

export const sentimentSummaryQuerySchema = z
  .object({
    subject_type: z.enum(["PRODUCT", "COMPETITOR", "BUSINESS"], {
      error: "subject_type must be one of 'PRODUCT', 'COMPETITOR', or 'BUSINESS'"
    }),
    subject_id: z
      .string()
      .uuid("subject_id must be a valid UUID")
      .optional(),
    country_context: z.string().trim().min(1).optional()
  })
  .superRefine((value, ctx) => {
    if (value.subject_type !== "BUSINESS" && !value.subject_id) {
      ctx.addIssue({
        code: "custom",
        path: ["subject_id"],
        message: `subject_id is required when subject_type is '${value.subject_type}'`
      });
    }
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

function sendValidationError(
  res: Response,
  error: z.ZodError
): void {
  sendApiError(res, ERROR_CODES.VALIDATION_ERROR, {
    details: error.issues.map((issue) => ({
      field: issue.path.join("."),
      message: issue.message
    }))
  });
}

export function validateSentimentAnalyzePendingQuery(
  req: AppRequest,
  res: Response,
  next: NextFunction
): void {
  const result = sentimentAnalyzePendingQuerySchema.safeParse(req.query);

  if (!result.success) {
    sendValidationError(res, result.error);
    return;
  }

  applyParsedQuery(req, result.data);
  next();
}

export function validateSentimentSummaryQuery(
  req: AppRequest,
  res: Response,
  next: NextFunction
): void {
  const result = sentimentSummaryQuerySchema.safeParse(req.query);

  if (!result.success) {
    sendValidationError(res, result.error);
    return;
  }

  applyParsedQuery(req, result.data);
  next();
}
