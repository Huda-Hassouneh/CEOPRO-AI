import { ERROR_CODES } from "../../../errors/error-codes.js";
import { ERROR_DEFINITIONS } from "../../../errors/error-defentions.js";
import plansRepo from "../repo/plans.repo.js";
import subscriptionRepo from "../repo/subscription.repo.js";
import { getAppConfig } from "../repo/repo.js";
import {
  AppConfig,
  Plan,
  Subscription
} from "../../../generated/prisma/client.js";
import { ErrorResponse, SuccessResponse } from "../../../types/response.js";
import { configKeys } from "../../../config/keys.config.js";
import { stripeService } from "../External Services/Payment providers/stripe/stripeService.js";

const tenantId = "d41eeac6-a61a-44c2-85c1-93d39a69b025";

export async function getPlansService(): Promise<SuccessResponse<Plan[]>> {
  const plans = await plansRepo.getAllPlans();
  return {
    success: true,
    message: "Plans fetched successfully ",
    data: plans
  };
}
export async function changePlanService(
  planId: string
): Promise<SuccessResponse<null> | ErrorResponse> {
  // check if plan exists

  const plan = await plansRepo.getPlanById(planId);
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
  const subscription = (await subscriptionRepo.getActiveSubscriptionByTenant(
    tenantId
  )) as Subscription;
  if (!subscription) {
    // Tenant has no subscription → should use initial checkout
    return {
      success: false,
      error: {
        code: ERROR_CODES.SUBSCRIPTION_NOT_FOUND,
        message: "Tenant does not have an active subscription",
        statusCode: 404
      }
    };
  }

  // 3. Same plan?
  console.log({ toUpdate: plan.id, old: subscription.planId });

  if (plan.id === subscription.planId) {
    return {
      success: false,
      error: {
        code: ERROR_CODES.SAME_PLAN,
        message: ERROR_DEFINITIONS[ERROR_CODES.SAME_PLAN].message,
        statusCode: ERROR_DEFINITIONS[ERROR_CODES.SAME_PLAN].statusCode
      }
    };
  }
  // 4. Retrieve existing Stripe subscription
  const stripeSubscription = await stripeService.retrieveSubscription(
    subscription.paymentProviderSubscriptionId!
  );
  // 5. Get existing Stripe subscription item
  const stripeSubscriptionItemId = stripeSubscription.items.data[0].id;
  console.log(stripeSubscription);

  const newSubscription = await stripeService.updateSubscription({
    paymentProviderPriceId: plan.paymentProviderPlanId!,
    paymentProviderSubscriptionId: stripeSubscription.id,
    stripeSubscriptionItemId
  });

  return {
    success: true,
    message: "Subscription plan changed successfully",
    data: null
  };
}
export async function createPlansService(
  data: Plan
): Promise<SuccessResponse<Plan> | ErrorResponse> {
  try {
    const isPlanExists = await plansRepo.getPlainByName(data.name);
    if (isPlanExists) {
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
    // create plan in configured paypal app
    // const token = await stripeService.generateAccessToken();
    const stripeProductKey = (await getAppConfig(
      configKeys.stripeAppConfigKey
    )) as AppConfig;

    const stripeCreatedPlan = await stripeService.createPlan(
      stripeProductKey?.value,
      {
        name: data.name,
        description: data.description || "",
        currency: data.currency,

        // Price
        unitAmount: Number(data.price),

        // Recurring period
        interval: data.billingIntervalUnit as "day" | "week" | "month" | "year",
        intervalCount: data.billingIntervalValue
      }
    );
    const insertedPlan = await plansRepo.createPlan({
      ...data,
      paymentProviderProductId: stripeProductKey.value,
      paymentProviderPlanId: stripeCreatedPlan.id
    });
    return {
      success: true,
      message: "Plan created successfully ",
      data: insertedPlan
    };
  } catch (err: any) {
    console.log(err);
    return {
      success: false,
      error: {
        code: "UNPROCCESSABLE_ENTITY",
        message: err.error,
        statusCode: 422
      }
    };
  }
}
export async function updatePlansService(
  id: string,
  data: Plan
): Promise<SuccessResponse<Plan> | ErrorResponse> {
  // check if id is exists at all
  const isPlanExists = await plansRepo.getPlanById(id);
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
  const plan = await plansRepo.updatePlan(id, data);
  return {
    success: true,
    message: "Plan created successfully ",
    data: plan
  };
}
