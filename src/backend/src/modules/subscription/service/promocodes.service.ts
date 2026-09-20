import { ERROR_CODES } from "../../../errors/error-codes.js";
import {
  getPromoCodeByCode,
  getPromoCodeForPlan,
  insertPromocode,
  updatePromocode,
  getAllPromocodes,
  getPromocodeById
} from "../repo/promocodes.repo.js";
import { PromoCode } from "../../../generated/prisma/client.js";
import { stripeService } from "../External Services/Payment providers/stripe/stripeService.js";
import { Decimal } from "@prisma/client/runtime/client";

type PromoCodeEssentials = {
  code: string;
  discountType: string;
  discountValue: Decimal;
  paymentProviderCoupon: string;
};

export type ServiceResult<T> =
  | { success: true; data: T; message?: string }
  | { success: false; code: string; message?: string };

export async function validatePromoCode(
  codeId: string,
  plan: string
): Promise<ServiceResult<PromoCodeEssentials>> {
  const promoCode = await getPromoCodeByCode(codeId);

  if (!promoCode) {
    return { success: false, code: ERROR_CODES.PROMO_CODE_NOT_FOUND };
  }

  const subscriptionPlan = await getPromoCodeForPlan(promoCode.id, plan);
  const now = new Date();

  if (!promoCode.isActive) {
    return { success: false, code: ERROR_CODES.PROMO_CODE_NOT_ACTIVE };
  }

  if (promoCode.usedCount >= promoCode.maxUses) {
    return { success: false, code: ERROR_CODES.PROMO_CODE_USAGE_LIMIT_REACHED };
  }

  if (now < promoCode.startsAt) {
    return { success: false, code: ERROR_CODES.PROMO_CODE_NOT_ACTIVE };
  }

  if (now > promoCode.expiresAt) {
    return { success: false, code: ERROR_CODES.PROMO_CODE_EXPIRED };
  }

  if (!subscriptionPlan) {
    return { success: false, code: ERROR_CODES.PROMO_CODE_NOT_APPLICABLE };
  }

  const { discountType, discountValue, code, paymentProviderCoupon } =
    promoCode;

  return {
    success: true,
    data: { code, discountType, discountValue, paymentProviderCoupon }
  };
}

export async function getPromocodeService(): Promise<
  ServiceResult<PromoCode[]>
> {
  const plans = await getAllPromocodes();
  return { success: true, data: plans };
}

export async function updatePromocodeService(
  id: string,
  data: PromoCode
): Promise<ServiceResult<PromoCode>> {
  const isPromocodeExists = await getPromocodeById(id);
  if (!isPromocodeExists) {
    return { success: false, code: ERROR_CODES.PROMO_CODE_NOT_FOUND };
  }

  // FIXED LOGIC: Check if the *new* code string is already taken by a *different* promo code
  if (data.code) {
    const codeInUse = await getPromoCodeByCode(data.code);
    if (codeInUse && codeInUse.id !== id) {
      return { success: false, code: ERROR_CODES.RESOURCE_ALREADY_EXISTS };
    }
  }

  const code = await stripeService.createPromoCode(
    data.discountType,
    Number(data.discountValue)
  );

  const promocode = await updatePromocode(id, {
    ...data,
    paymentProviderCoupon: code.id
  });

  return { success: true, data: promocode };
}

export async function createPromocodeService(
  data: PromoCode
): Promise<ServiceResult<PromoCode>> {
  const isPromocodeExists = await getPromoCodeByCode(data.code);

  if (isPromocodeExists) {
    return { success: false, code: ERROR_CODES.RESOURCE_ALREADY_EXISTS };
  }

  const code = await stripeService.createPromoCode(
    data.discountType,
    Number(data.discountValue)
  );

  const insertedPromocode = await insertPromocode({
    ...data,
    paymentProviderCoupon: code.id
  });

  return { success: true, data: insertedPromocode };
}
