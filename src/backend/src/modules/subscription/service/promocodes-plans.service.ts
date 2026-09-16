import { ERROR_CODES } from "../../../errors/error-codes.js";
import { ERROR_DEFINITIONS } from "../../../errors/error-defentions.js";
import plansRepo from "../repo/plans.repo.js";
import { getPromocodeById } from "../repo/promocodes.repo.js";
import {
  getPlanPromoCode,
  linkPlanPromoCode
} from "../repo/promocodes-plans.repo.js";

import { ErrorResponse, SuccessResponse } from "../../../types/response.js";

export async function linkPromoCodePlan(
  planId: string,
  promoCodeId: string
): Promise<SuccessResponse<null> | ErrorResponse> {
  // check if promocode exists

  const promoCode = await getPromocodeById(promoCodeId);

  const plan = await plansRepo.getPlanById(planId);
  if (!promoCode) {
    return {
      success: false,
      error: {
        code: ERROR_CODES.PROMO_CODE_NOT_FOUND,
        message: ERROR_DEFINITIONS[ERROR_CODES.PROMO_CODE_NOT_FOUND].message,
        statusCode:
          ERROR_DEFINITIONS[ERROR_CODES.PROMO_CODE_NOT_FOUND].statusCode
      }
    };
  }
  if (!plan) {
    return {
      success: false,
      error: {
        code: ERROR_CODES.PLAN_NOT_FOUND,
        message: ERROR_DEFINITIONS[ERROR_CODES.PLAN_NOT_FOUND].message,
        statusCode: ERROR_DEFINITIONS[ERROR_CODES.PLAN_NOT_FOUND].statusCode
      }
    };
  }

  const isPlanPromoCodeLinked = await getPlanPromoCode(planId, promoCodeId);
  if (isPlanPromoCodeLinked) {
    return {
      success: false,
      error: {
        code: ERROR_CODES.RESOURCE_ALREADY_EXISTS,
        message: ERROR_DEFINITIONS[ERROR_CODES.RESOURCE_ALREADY_EXISTS].message,
        statusCode:
          ERROR_DEFINITIONS[ERROR_CODES.RESOURCE_ALREADY_EXISTS].statusCode
      }
    };
  }
  await linkPlanPromoCode(planId, promoCodeId);
  return {
    success: true,
    message: "Promo code linked to plan successfully",
    data: null
  };
}
