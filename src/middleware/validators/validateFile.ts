import type { NextFunction, Response } from "express";
import { ERROR_CODES } from "../../errors/error-codes.js";
import { ERROR_DEFINITIONS } from "../../errors/error-definitions.js";
import { validateExtractionUpload } from "../../modules/dataconnection/types/dataconnection.validation.js";
import { errorResponse } from "../../types/response.js";
import type { AppRequest } from "../../types/request.js";

const ERROR_DETAILS = {
  MISSING_FILE: "A multipart file is required in field 'file'.",
  INVALID_EXTENSION:
    "Allowed file extensions are .csv, .xlsx, .xlsm, and .pdf.",
  INVALID_SIZE: "The file is empty or has an invalid size.",
  FILE_TOO_LARGE: "The file exceeds the configured upload size limit.",
  CONTENT_EXTENSION_MISMATCH:
    "The file content does not match its extension, or the file is malformed.",
  TEMPLATE_MISMATCH:
    "The file does not match the CEOPRO sales template. Use the required product_name, quantity, unit_price, currency, and transaction_date columns."
} as const;

export default function validateFile(
  req: AppRequest,
  res: Response,
  next: NextFunction
) {
  const validationError = validateExtractionUpload(
    req.file
      ? {
          originalname: req.file.originalname,
          size: req.file.size,
          buffer: req.file.buffer
        }
      : undefined
  );

  if (!validationError) {
    next();
    return;
  }

  const isTooLarge = validationError === "FILE_TOO_LARGE";
  const code = isTooLarge
    ? ERROR_CODES.FILE_SIZE_LIMIT_EXCEEDED
    : ERROR_CODES.INVALID_FILE_UPLOAD;
  const definition = ERROR_DEFINITIONS[code];

  res
    .status(definition.statusCode)
    .json(
      errorResponse(
        definition.message,
        definition.statusCode,
        code,
        ERROR_DETAILS[validationError]
      )
    );
}
