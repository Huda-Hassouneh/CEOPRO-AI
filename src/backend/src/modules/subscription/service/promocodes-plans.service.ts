import { ERROR_CODES } from "../../../errors/error-codes.js";
import plansRepo from "../repo/plans.repo.js";
import { getPromocodeById } from "../repo/promocodes.repo.js";
import {
  getPlanPromoCode,
  linkPlanPromoCode
} from "../repo/promocodes-plans.repo.js";

export type ServiceResult<T> =
  | { success: true; data: T }
  | { success: false; code: string; message?: string };

export async function linkPromoCodePlan(
  planId: string,
  promoCodeId: string
): Promise<ServiceResult<null>> {
  // 1. Check if promocode exists
  const promoCode = await getPromocodeById(promoCodeId);
  if (!promoCode) {
    return { success: false, code: ERROR_CODES.PROMO_CODE_NOT_FOUND };
  }

  // 2. Check if plan exists
  const plan = await plansRepo.getPlanById(planId);
  if (!plan) {
    return { success: false, code: ERROR_CODES.PLAN_NOT_FOUND };
  }

  // 3. Check if they are already linked
  const isPlanPromoCodeLinked = await getPlanPromoCode(planId, promoCodeId);
  if (isPlanPromoCodeLinked) {
    return { success: false, code: ERROR_CODES.RESOURCE_ALREADY_EXISTS };
  }

  // 4. Perform the linking action
  await linkPlanPromoCode(planId, promoCodeId);

  return { success: true, data: null };
}
