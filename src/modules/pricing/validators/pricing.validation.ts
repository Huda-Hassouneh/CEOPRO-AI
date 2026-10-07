import type { NextFunction, Response } from "express";
import { z } from "zod";
import { ERROR_CODES } from "../../../errors/error-codes.js";
import type { AppRequest } from "../../../types/request.js";
import { sendApiError } from "../../../utils/http.js";

export const pricingRecommendationQuerySchema = z.object({
  product_id: z
    .string({ error: "product_id query parameter is required" })
    .uuid("product_id must be a valid UUID")
});

export function validatePricingRecommendationQuery(
  req: AppRequest,
  res: Response,
  next: NextFunction
): void {
  const result = pricingRecommendationQuerySchema.safeParse(req.query);

  if (!result.success) {
    sendApiError(res, ERROR_CODES.VALIDATION_ERROR, {
      details: result.error.issues.map((issue) => ({
        field: issue.path.join("."),
        message: issue.message
      }))
    });
    return;
  }

  Object.defineProperty(req, "query", {
    value: result.data,
    writable: true,
    enumerable: true,
    configurable: true
  });

  next();
}
import path from "node:path";

const MAX_UPLOAD_FILENAME_LENGTH = 180;

export function safeUploadName(originalName: string): string {
  if (typeof originalName !== "string" || !originalName.trim()) {
    return "upload";
  }

  /*
   * Browsers normally send only the filename, but some clients may send:
   *
   *   C:\\fakepath\\report.xlsx
   *   ../../report.csv
   *
   * Convert Windows separators first, then keep only the final component.
   */
  const baseName = path.basename(originalName.replace(/\\/g, "/"));

  /*
   * Remove control characters that should never appear in multipart
   * filenames or persisted metadata.
   */
  const withoutControls = baseName.replace(/[\u0000-\u001F\u007F]/g, "");

  /*
   * Keep the extension because the AI extraction service validates
   * supported file types using the uploaded filename/content.
   */
  const extension = path.extname(withoutControls).toLowerCase();

  let stem = path.basename(withoutControls, path.extname(withoutControls));

  /*
   * Preserve normal Latin/Arabic/Unicode letters and numbers while replacing
   * filesystem/header-unfriendly characters with "_".
   */
  stem = stem
    .normalize("NFKC")
    .replace(/[^\p{L}\p{N}._ -]+/gu, "_")
    .replace(/\s+/g, " ")
    .replace(/_+/g, "_")
    .replace(/^\.+/, "")
    .trim();

  if (!stem) {
    stem = "upload";
  }

  /*
   * Leave enough room for the extension.
   */
  const maxStemLength = Math.max(
    1,
    MAX_UPLOAD_FILENAME_LENGTH - extension.length
  );

  if (stem.length > maxStemLength) {
    stem = stem.slice(0, maxStemLength).trim();
  }

  return `${stem}${extension}`;
}
