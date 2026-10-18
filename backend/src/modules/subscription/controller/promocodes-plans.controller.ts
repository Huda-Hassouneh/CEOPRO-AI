import type { Response } from "express";
import { linkPromoCodePlan } from "../service/promocodes-plans.service.js";
import type { SuccessResponse } from "../../../types/response.js";
import type { AppRequest } from "../../../types/request.js";
import { sendApiError } from "../../../utils/http.js";

export async function linkPlanWithPromocodeHandler(
  req: AppRequest,
  resp: Response
) {
  const result = await linkPromoCodePlan(
    String(req.params.planId),
    String(req.params.promoCodeId),
    String(req.tenant_id)
  );

  if (!result.success) {
    return sendApiError(resp, result.code);
  }

  const response: SuccessResponse<null> = {
    success: true,
    message: "Promo code linked to plan successfully",
    data: result.data
  };
  return resp.status(201).json(response);
}
