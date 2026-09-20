import { Request, Response } from "express";
import { usageService } from "../service/usage.service.js";
import { successResponse, errorResponse } from "../../../types/response.js";
import { ERROR_CODES } from "../../../errors/error-codes.js";
import { ERROR_DEFINITIONS } from "../../../errors/error-defentions.js";

export const usageController = {
  getDashboard: async (req: any, res: Response): Promise<void> => {
    try {
      const tenantId = req.tenant_id;

      if (!tenantId) {
        const errDef = ERROR_DEFINITIONS[ERROR_CODES.INVALID_REQUEST];
        res
          .status(errDef.statusCode)
          .json(
            errorResponse(
              errDef.message,
              errDef.statusCode,
              ERROR_CODES.INVALID_REQUEST,
              "Tenant context missing."
            )
          );
        return;
      }

      const dashboard = await usageService.getTenantUsageDashboard(tenantId);

      res
        .status(200)
        .json(
          successResponse(dashboard, "Usage dashboard retrieved successfully")
        );
    } catch (error: any) {
      // Check if the service threw a known, mapped error
      if (error.message === ERROR_CODES.SUBSCRIPTION_NOT_FOUND) {
        const errDef = ERROR_DEFINITIONS[ERROR_CODES.SUBSCRIPTION_NOT_FOUND];
        res
          .status(errDef.statusCode)
          .json(
            errorResponse(
              errDef.message,
              errDef.statusCode,
              ERROR_CODES.SUBSCRIPTION_NOT_FOUND
            )
          );
        return;
      }

      // Fallback for unhandled/internal server exceptions
      console.error("Usage Dashboard Error:", error);
      const errDef = ERROR_DEFINITIONS[ERROR_CODES.INTERNAL_SERVER_ERROR];
      res
        .status(errDef.statusCode)
        .json(
          errorResponse(
            errDef.message,
            errDef.statusCode,
            ERROR_CODES.INTERNAL_SERVER_ERROR,
            error instanceof Error ? error.message : error
          )
        );
    }
  }
};
