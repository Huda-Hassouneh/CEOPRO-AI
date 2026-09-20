import { Request, Response } from "express";
import { linkPromoCodePlan } from "../service/promocodes-plans.service.js";
import { ErrorResponse, SuccessResponse } from "../../../types/response.js";
import { ERROR_DEFINITIONS } from "../../../errors/error-defentions.js";

function handleError(resp: Response, code: string) {
  const safeCode = code as keyof typeof ERROR_DEFINITIONS;
  const errorDef = ERROR_DEFINITIONS[safeCode] || {
    message: "An unexpected error occurred",
    statusCode: 400
  };

  const errorResponse: ErrorResponse = {
    success: false,
    error: {
      code: code,
      message: errorDef.message,
      statusCode: errorDef.statusCode
    }
  };

  return resp.status(errorDef.statusCode).json(errorResponse);
}

export async function linkPlanWithPromocodeHandler(
  req: Request,
  resp: Response
) {
  const planId: string = req.params.planId as string;
  const promoCodeId: string = req.params.promoCodeId as string;

  const result = await linkPromoCodePlan(planId, promoCodeId);

  if (!result.success) {
    return handleError(resp, result.code);
  }

  const response: SuccessResponse<null> = {
    success: true,
    message: "Promo code linked to plan successfully",
    data: result.data
  };

  return resp.status(201).json(response);
}
