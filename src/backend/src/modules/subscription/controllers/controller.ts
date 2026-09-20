import { Request, Response } from "express";
import { onBoardingService } from "../service/service.js";
import { ERROR_DEFINITIONS } from "../../../errors/error-defentions.js";
import { configKeys } from "../../../config/keys.config.js";
import { ErrorResponse, SuccessResponse } from "../../../types/response.js";

export async function onBoardingHandler(req: Request, resp: Response) {
  const result = await onBoardingService();
  if (!result.success) {
    const safeCode = result.code as keyof typeof ERROR_DEFINITIONS;
    const errorDef = ERROR_DEFINITIONS[safeCode];

    const errorResponse: ErrorResponse = {
      success: false,
      error: {
        code: result.code,
        message: errorDef.message,
        statusCode: errorDef.statusCode
      }
    };

    // IMPORTANT: Return early so the code stops executing
    return resp.status(errorDef.statusCode).json(errorResponse);
  }

  const successResponse: SuccessResponse<null> = {
    success: true,
    data: result.data,
    message: `${configKeys.stripeAppConfigKey} inserted successfully.`
  };

  return resp.status(201).json(successResponse);
}
