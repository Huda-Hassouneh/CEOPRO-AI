import { Request, RequestHandler, Response } from "express";
import { ERROR_DEFINITIONS } from "../errors/error-defentions.js";
import { ERROR_CODES } from "../errors/error-codes.js";
import { errorResponse } from "../types/response.js";
import { getTokenPayload, isTokenValid } from "../utils/token.js";

export function validateHeader(req: Request, resp: Response, next: () => any) {
  const token = req.headers.authorization;
  if (!token) {
    const error = ERROR_DEFINITIONS[ERROR_CODES.UNAUTHORIZED];

    return resp
      .status(error.statusCode)
      .json(
        errorResponse(error.message, error.statusCode, ERROR_CODES.UNAUTHORIZED)
      );
  }

  next();
}
export function validateToken(req: Request, resp: Response, next: () => any) {
  const token = req.headers.authorization!?.split(" ")[1];
  if (!isTokenValid(token)) {
    const error = ERROR_DEFINITIONS[ERROR_CODES.INVALID_TOKEN];

    return resp
      .status(error.statusCode)
      .json(
        errorResponse(
          error.message,
          error.statusCode,
          ERROR_CODES.INVALID_TOKEN
        )
      );
  }

  next();
}
export function isAdmin(req: Request, resp: Response, next: () => any) {
  const token = req.headers.authorization!?.split(" ")[1];

  const admin = getTokenPayload(token)?.role === "admin";

  if (!admin) {
    const error = ERROR_DEFINITIONS[ERROR_CODES.FORBIDDEN];

    return resp
      .status(error.statusCode)
      .json(
        errorResponse(error.message, error.statusCode, ERROR_CODES.FORBIDDEN)
      );
  }
  next();
}
