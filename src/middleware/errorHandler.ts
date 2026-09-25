import type { ErrorRequestHandler, RequestHandler } from "express";
import { ERROR_CODES } from "../errors/error-codes.js";
import { ERROR_DEFINITIONS } from "../errors/error-definitions.js";
import { errorResponse } from "../types/response.js";

export const notFoundHandler: RequestHandler = (_req, res) => {
  const def = ERROR_DEFINITIONS[ERROR_CODES.RESOURCE_NOT_FOUND];
  res.status(def.statusCode).json(
    errorResponse(def.message, def.statusCode, ERROR_CODES.RESOURCE_NOT_FOUND)
  );
};

export const globalErrorHandler: ErrorRequestHandler = (err, _req, res, next) => {
  console.error("Unhandled request error:", err);
  if (res.headersSent) {
    next(err);
    return;
  }
  const def = ERROR_DEFINITIONS[ERROR_CODES.INTERNAL_SERVER_ERROR];
  res.status(def.statusCode).json(
    errorResponse(def.message, def.statusCode, ERROR_CODES.INTERNAL_SERVER_ERROR)
  );
};
