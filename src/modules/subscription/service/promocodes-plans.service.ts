import { stripeService } from "../External Services/Payment providers/stripe/stripeService.js";
import { ERROR_CODES } from "../../../errors/error-codes.js";
import plansRepo from "../repo/plans.repo.js";
import { getPromocodeById } from "../repo/promocodes.repo.js";
import {
  getPlanPromoCode,
  linkPlanPromoCode
} from "../repo/promocodes-plans.repo.js";

import type { ServiceResult } from "../../../types/service.js";

async function linkPromoCodePlanInternal(
  planId: string,
  promoCodeId: string,
  tenantId?: string,
  allowAnyCustomPlan = false
): Promise<ServiceResult<null>> {
  const promoCode = await getPromocodeById(promoCodeId);
  if (!promoCode) {
    return { success: false, code: ERROR_CODES.PROMO_CODE_NOT_FOUND };
  }

  const plan = await plansRepo.getPlanById(planId);
  if (!plan) {
    return { success: false, code: ERROR_CODES.PLAN_NOT_FOUND };
  }

  if (
    plan.planType === "custom" &&
    !allowAnyCustomPlan &&
    plan.tenantId !== tenantId
  ) {
    return { success: false, code: ERROR_CODES.PLAN_NOT_AVAILABLE };
  }

  if (promoCode.discountType === "fixed_amount") {
    const stripeCoupon = await stripeService.retrievePromoCode(
      promoCode.paymentProviderCoupon
    );
    if (
      !stripeCoupon.currency ||
      stripeCoupon.currency.toUpperCase() !== plan.currency.toUpperCase()
    ) {
      return { success: false, code: ERROR_CODES.PROMO_CODE_CURRENCY_MISMATCH };
    }
  }

  const isPlanPromoCodeLinked = await getPlanPromoCode(planId, promoCodeId);
  if (isPlanPromoCodeLinked) {
    return { success: false, code: ERROR_CODES.RESOURCE_ALREADY_EXISTS };
  }

  await linkPlanPromoCode(planId, promoCodeId);
  return { success: true, data: null };
}

export async function linkPromoCodePlan(
  planId: string,
  promoCodeId: string,
  tenantId: string
): Promise<ServiceResult<null>> {
  return linkPromoCodePlanInternal(planId, promoCodeId, tenantId, false);
}

export async function linkPromoCodePlanForPlatform(
  planId: string,
  promoCodeId: string
): Promise<ServiceResult<null>> {
  return linkPromoCodePlanInternal(planId, promoCodeId, undefined, true);
}
