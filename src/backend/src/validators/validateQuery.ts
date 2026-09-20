import { NextFunction, Request, Response } from "express";
import { ZodError } from "zod";
import { AnyZodObject, ZodSchema } from "zod/v3";

export const validateQuery = (schema: any) => {
  return (req: Request, res: Response, next: NextFunction): void => {
    try {
      req.query = schema.parse(req.query);
      next();
    } catch (error) {
      if (error instanceof ZodError) {
        res.status(400).json({
          error: "Invalid query parameters",
          details: error.issues.map((e) => ({
            field: e.path.join("."),
            message: e.message
          }))
        });
        return;
      }
      next(error);
    }
  };
};
