import { ERROR_CODES } from "../../../errors/error-codes.js";
import {
  countPromoRedemptionsForTenant,
  getAllPromocodes,
  getPromoCodeByCode,
  getPromoCodeForPlan,
  getPromocodeById,
  insertPromocode,
  updatePromocode
} from "../repo/promocodes.repo.js";
import type { PromoCode } from "../../../generated/prisma/client.js";
import type { CreatePromoCodeDTO, UpdatePromoCodeDTO } from "../../../DTO/promoCode.dto.js";
import { stripeService } from "../External Services/Payment providers/stripe/stripeService.js";
import { getRequiredEnv } from "../../../config/env.js";

import type { ServiceResult } from "../../../types/service.js";

type PromoCodeEssentials = Pick<
  PromoCode,
  "code" | "discountType" | "discountValue" | "paymentProviderCoupon"
>;

export async function validatePromoCode(
  codeId: string,
  planId: string,
  tenantId?: string
): Promise<ServiceResult<PromoCodeEssentials>> {
  const promoCode = await getPromoCodeByCode(codeId);
  if (!promoCode) return { success: false, code: ERROR_CODES.PROMO_CODE_NOT_FOUND };

  const [subscriptionPlan, tenantRedemptions] = await Promise.all([
    getPromoCodeForPlan(promoCode.id, planId),
    tenantId ? countPromoRedemptionsForTenant(promoCode.id, tenantId) : Promise.resolve(0)
  ]);
  const now = new Date();

  if (!promoCode.isActive || now < promoCode.startsAt) {
    return { success: false, code: ERROR_CODES.PROMO_CODE_NOT_ACTIVE };
  }
  if (now > promoCode.expiresAt) {
    return { success: false, code: ERROR_CODES.PROMO_CODE_EXPIRED };
  }
  if (promoCode.usedCount >= promoCode.maxUses || tenantRedemptions >= promoCode.maxUsesPerUser) {
    return { success: false, code: ERROR_CODES.PROMO_CODE_USAGE_LIMIT_REACHED };
  }
  if (!subscriptionPlan) {
    return { success: false, code: ERROR_CODES.PROMO_CODE_NOT_APPLICABLE };
  }

  const { discountType, discountValue, code, paymentProviderCoupon } = promoCode;
  return { success: true, data: { code, discountType, discountValue, paymentProviderCoupon } };
}

export async function getPromocodeService(): Promise<ServiceResult<PromoCode[]>> {
  return { success: true, data: await getAllPromocodes() };
}

export async function updatePromocodeService(
  id: string,
  data: UpdatePromoCodeDTO
): Promise<ServiceResult<PromoCode>> {
  const existing = await getPromocodeById(id);
  if (!existing) return { success: false, code: ERROR_CODES.PROMO_CODE_NOT_FOUND };

  if (data.code) {
    const codeInUse = await getPromoCodeByCode(data.code);
    if (codeInUse && codeInUse.id !== id) {
      return { success: false, code: ERROR_CODES.RESOURCE_ALREADY_EXISTS };
    }
  }

  const discountChanged = data.discountType !== undefined || data.discountValue !== undefined;
  let paymentProviderCoupon = existing.paymentProviderCoupon;
  if (discountChanged) {
    const nextDiscountType = data.discountType ?? existing.discountType;
    const coupon = await stripeService.createPromoCode(
      nextDiscountType,
      Number(data.discountValue ?? existing.discountValue),
      "once",
      nextDiscountType === "fixed_amount"
        ? getRequiredEnv("PROMO_FIXED_AMOUNT_CURRENCY")
        : undefined
    );
    paymentProviderCoupon = coupon.id;
  }

  const promocode = await updatePromocode(id, {
    ...data,
    ...(discountChanged ? { paymentProviderCoupon } : {})
  });
  return { success: true, data: promocode };
}

export async function createPromocodeService(
  data: CreatePromoCodeDTO
): Promise<ServiceResult<PromoCode>> {
  if (await getPromoCodeByCode(data.code)) {
    return { success: false, code: ERROR_CODES.RESOURCE_ALREADY_EXISTS };
  }

  const coupon = await stripeService.createPromoCode(
    data.discountType,
    data.discountValue,
    "once",
    data.discountType === "fixed_amount"
      ? getRequiredEnv("PROMO_FIXED_AMOUNT_CURRENCY")
      : undefined
  );

  const inserted = await insertPromocode({
    ...data,
    paymentProviderCoupon: coupon.id
  });
  return { success: true, data: inserted };
}
