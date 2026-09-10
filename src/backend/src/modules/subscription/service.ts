import { ERROR_CODES } from "../../errors/error-codes.js";
import {
  ERROR_DEFINITION_ITEM,
  ERROR_DEFINITIONS
} from "../../errors/error-defentions.js";
import {
  createPlan,
  getAllPlans,
  getPlanById,
  getPlainByName,
  getPromoCodeByCode,
  getPromoCodeForPlan,
  updatePlan,
  insertPromocode,
  updatePromocode,
  getAllPromocodes,
  getPromocodeById,
  getPlanPromoCode,
  linkPlanPromoCode
} from "./repo.js";
import { Plan, PromoCode } from "../../generated/prisma/client.js";
import { Decimal } from "@prisma/client/runtime/client";
import { ErrorResponse, SuccessResponse } from "../../types/response.js";

type PromoCodeEseentials = {
  code: string;
  discountType: string;
  discountValue: Decimal;
};
export async function validatePromoCode(
  code: string,
  plan: string
): Promise<SuccessResponse<PromoCodeEseentials> | ErrorResponse> {
  const promoCode = await getPromoCodeByCode(code);
  const subscriptionPlan = await getPromoCodeForPlan(code, plan);
  const now = new Date();

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
  const { discountType, discountValue } = promoCode;
  return {
    success: true,
    message: "Promo code is valid",
    data: { code, discountType, discountValue }
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
  const promocode = await updatePromocode(id, data);
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
  const insertedPromocode = await insertPromocode(data);

  return {
    success: true,
    data: insertedPromocode,
    message: "Promocode created successfully"
  };
}
export async function getPlansService(): Promise<SuccessResponse<Plan[]>> {
  const plans = await getAllPlans();
  return {
    success: true,
    message: "Plans fetched successfully ",
    data: plans
  };
}
export async function createPlansService(
  data: Plan
): Promise<SuccessResponse<Plan> | ErrorResponse> {
  const isPlanExists = await getPlainByName(data.name);
  if (isPlanExists) {
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
  const insertedPlan = await createPlan(data);
  return {
    success: true,
    message: "Plan created successfully ",
    data: insertedPlan
  };
}

export async function updatePlansService(
  id: string,
  data: Plan
): Promise<SuccessResponse<Plan> | ErrorResponse> {
  // check if id is exists at all
  const isPlanExists = await getPlanById(id);
  if (!isPlanExists) {
    return {
      success: false,
      error: {
        code: ERROR_CODES.PLAN_NOT_FOUND,
        message: ERROR_DEFINITIONS[ERROR_CODES.PLAN_NOT_FOUND].message,
        statusCode: ERROR_DEFINITIONS[ERROR_CODES.PLAN_NOT_FOUND].statusCode
      }
    };
  }
  if (data.name) {
    if (isPlanExists.id !== id) {
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
  const plan = await updatePlan(id, data);
  return {
    success: true,
    message: "Plan created successfully ",
    data: plan
  };
}
export async function linkPromoCodePlan(
  planId: string,
  promoCodeId: string
): Promise<SuccessResponse<null> | ErrorResponse> {
  // check if promocode exists

  const promoCode = await getPromocodeById(promoCodeId);

  const plan = await getPlanById(planId);
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
