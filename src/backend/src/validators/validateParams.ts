import { Request, Response, NextFunction } from "express";
import { z } from "zod";
import { ERROR_CODES } from "../errors/error-codes.js";
import { ERROR_DEFINITIONS } from "../errors/error-defentions.js";
import { errorResponse } from "../types/response.js";

export function validateParams(schema: z.ZodType) {
  return (req: Request, res: Response, next: NextFunction) => {
    const result = schema.safeParse(req.params);

    if (!result.success) {
      const error = ERROR_DEFINITIONS[ERROR_CODES.VALIDATION_ERROR];

      return res
        .status(error.statusCode)
        .json(
          errorResponse(
            error.message,
            ERROR_DEFINITIONS[ERROR_CODES.VALIDATION_ERROR].statusCode,
            ERROR_CODES.VALIDATION_ERROR,
            result.error.flatten()
          )
        );
    }

    req.params = result.data;
    next();
  };
}
