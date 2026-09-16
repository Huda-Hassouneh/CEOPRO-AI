import { ERROR_CODES } from "../../../errors/error-codes.js";
import { ERROR_DEFINITIONS } from "../../../errors/error-defentions.js";
import {
  getPromoCodeByCode,
  getPromoCodeForPlan,
  insertPromocode,
  updatePromocode,
  getAllPromocodes,
  getPromocodeById
} from "../repo/promocodes.repo.js";
import { PromoCode } from "../../../generated/prisma/client.js";
import { ErrorResponse, SuccessResponse } from "../../../types/response.js";

import { stripeService } from "../External Services/Payment providers/stripe/stripeService.js";
import { Decimal } from "@prisma/client/runtime/client";
type PromoCodeEseentials = {
  code: string;
  discountType: string;
  discountValue: Decimal;
  paymentProviderCoupon: string;
};
export async function validatePromoCode(
  codeId: string,
  plan: string
): Promise<SuccessResponse<PromoCodeEseentials> | ErrorResponse> {
  const promoCode = await getPromoCodeByCode(codeId);

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
  const subscriptionPlan = await getPromoCodeForPlan(promoCode.id, plan);
  const now = new Date();

  if (!promoCode.isActive) {
    return {
      success: false,
      error: {
        code: ERROR_CODES.PROMO_CODE_NOT_ACTIVE,
        message: ERROR_DEFINITIONS[ERROR_CODES.PROMO_CODE_NOT_ACTIVE].message,
        statusCode:
          ERROR_DEFINITIONS[ERROR_CODES.PROMO_CODE_NOT_ACTIVE].statusCode
      }
    };
  }

  if (promoCode.usedCount >= promoCode.maxUses) {
    return {
      success: false,
      error: {
        code: ERROR_CODES.PROMO_CODE_USAGE_LIMIT_REACHED,
        message:
          ERROR_DEFINITIONS[ERROR_CODES.PROMO_CODE_USAGE_LIMIT_REACHED].message,
        statusCode:
          ERROR_DEFINITIONS[ERROR_CODES.PROMO_CODE_USAGE_LIMIT_REACHED]
            .statusCode
      }
    };
  }

  if (now < promoCode.startsAt) {
    return {
      success: false,
      error: {
        code: ERROR_CODES.PROMO_CODE_NOT_ACTIVE,
        message: ERROR_DEFINITIONS[ERROR_CODES.PROMO_CODE_NOT_ACTIVE].message,
        statusCode:
          ERROR_DEFINITIONS[ERROR_CODES.PROMO_CODE_NOT_ACTIVE].statusCode
      }
    };
  }

  if (now > promoCode.expiresAt) {
    return {
      success: false,
      error: {
        code: ERROR_CODES.PROMO_CODE_EXPIRED,
        message: ERROR_DEFINITIONS[ERROR_CODES.PROMO_CODE_EXPIRED].message,
        statusCode: ERROR_DEFINITIONS[ERROR_CODES.PROMO_CODE_EXPIRED].statusCode
      }
    };
  }

  if (!subscriptionPlan) {
    return {
      success: false,
      error: {
        code: ERROR_CODES.PROMO_CODE_NOT_APPLICABLE,

        message:
          ERROR_DEFINITIONS[ERROR_CODES.PROMO_CODE_NOT_APPLICABLE].message,
        statusCode:
          ERROR_DEFINITIONS[ERROR_CODES.PROMO_CODE_NOT_APPLICABLE].statusCode
      }
    };
  }
  const { discountType, discountValue, code, paymentProviderCoupon } =
    promoCode;
  return {
    success: true,
    message: "Promo code is valid",
    data: { code, discountType, discountValue, paymentProviderCoupon }
  };
}
export async function getPromocodeService(): Promise<
  SuccessResponse<PromoCode[]>
> {
  const plans = await getAllPromocodes();
  return {
    success: true,
    message: "Promocodes fetched successfully ",
    data: plans
  };
}
export async function updatePromocodeService(
  id: string,
  data: PromoCode
): Promise<SuccessResponse<PromoCode> | ErrorResponse> {
  // check if id is exists at all
  const isPromocodeExists = await getPromocodeById(id);
  if (!isPromocodeExists) {
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
  if (data.code) {
    if (isPromocodeExists.id !== id) {
      return {
        success: false,
        error: {
          code: ERROR_CODES.RESOURCE_ALREADY_EXISTS,
          message:
            ERROR_DEFINITIONS[ERROR_CODES.RESOURCE_ALREADY_EXISTS].message,
          statusCode:
            ERROR_DEFINITIONS[ERROR_CODES.RESOURCE_ALREADY_EXISTS].statusCode
        }
      };
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
  return {
    success: true,
    message: "Promocode updated successfully ",
    data: promocode
  };
}
export async function createPromocodeService(
  data: PromoCode
): Promise<SuccessResponse<PromoCode> | ErrorResponse> {
  const isPromocodeExists = await getPromoCodeByCode(data.code);

  if (isPromocodeExists) {
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
  const code = await stripeService.createPromoCode(
    data.discountType,
    Number(data.discountValue)
  );
  console.log(code);

  const insertedPromocode = await insertPromocode({
    ...data,
    paymentProviderCoupon: code.id
  });

  return {
    success: true,
    data: insertedPromocode,
    message: "Promocode created successfully"
  };
}
