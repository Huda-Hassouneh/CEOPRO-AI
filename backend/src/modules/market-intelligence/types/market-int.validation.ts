import type { NextFunction, Response } from "express";
import { z } from "zod";
import { ERROR_CODES } from "../../../errors/error-codes.js";
import type { AppRequest } from "../../../types/request.js";
import { sendApiError } from "../../../utils/http.js";

export const marketOverviewQuerySchema = z.object({
  productId: z.string().uuid().transform((value) => value.toLowerCase()).optional(),
  periodDays: z.enum(["30", "90"]).optional()
});

export function validateMarketOverviewQuery(req: AppRequest, res: Response, next: NextFunction): void {
  const result = marketOverviewQuerySchema.safeParse(req.query);
  if (!result.success) {
    sendApiError(res, ERROR_CODES.VALIDATION_ERROR, {
      details: result.error.issues.map((issue) => ({
        field: issue.path.join("."), message: issue.message
      }))
    });
    return;
  }
  Object.defineProperty(req, "query", {
    value: result.data, writable: true, enumerable: true, configurable: true
  });
  next();
}
