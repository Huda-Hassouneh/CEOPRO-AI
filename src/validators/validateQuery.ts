import type { NextFunction, Request, Response } from "express";
import { z } from "zod";

export const validateQuery = (schema: z.ZodType) => {
  return (req: Request, res: Response, next: NextFunction): void => {
    const result = schema.safeParse(req.query);
    console.log({ result: result });
    if (!result.success) {
      res.status(400).json({
        error: "Invalid query parameters",
        details: result.error.issues.map((issue) => ({
          field: issue.path.join("."),
          message: issue.message
        }))
      });
      return;
    }
    Object.defineProperty(req, "query", {
      value: result.data, // e.g., schema.parse(req.query)
      writable: true,
      enumerable: true,
      configurable: true
    });

    next();
  };
};
