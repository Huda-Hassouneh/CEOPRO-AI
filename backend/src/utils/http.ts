import type { Response } from "express";
import { ERROR_CODES, type ErrorCode } from "../errors/error-codes.js";
import { ERROR_DEFINITIONS } from "../errors/error-definitions.js";
import { errorResponse } from "../types/response.js";

export function isErrorCode(code: string): code is ErrorCode {
  return Object.prototype.hasOwnProperty.call(ERROR_DEFINITIONS, code);
}

export function sendApiError(
  res: Response,
  code: string,
  options: { details?: unknown; publicMessage?: string } = {}
) {
  const resolvedCode = isErrorCode(code)
    ? code
    : ERROR_CODES.INTERNAL_SERVER_ERROR;
  const definition = ERROR_DEFINITIONS[resolvedCode];

  return res.status(definition.statusCode).json(
    errorResponse(
      options.publicMessage ?? definition.message,
      definition.statusCode,
      resolvedCode,
      options.details
    )
  );
}
