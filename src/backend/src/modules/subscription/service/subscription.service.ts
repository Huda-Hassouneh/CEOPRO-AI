import { ERROR_CODES } from "../../../errors/error-codes.js";
import { ERROR_DEFINITIONS } from "../../../errors/error-defentions.js";
import plansRepo from "../repo/plans.repo.js";
import subscriptionRepo from "../repo/subscription.repo.js";
import { validatePromoCode } from "./promocodes.service.js";
import { Plan, PromoCode } from "../../../generated/prisma/client.js";
import { ErrorResponse, SuccessResponse } from "../../../types/response.js";
import { UUID } from "node:crypto";

import { stripeService } from "../External Services/Payment providers/stripe/stripeService.js";
import { createCustomerWithClock } from "../External Services/Payment providers/stripe/stripe.test-clock.js";
const URLS = {
  success: "http://localhost:3000/subscription/success",
  cancel: "http://localhost:3000/subscription/cancel"
};
const tenantId = "d41eeac6-a61a-44c2-85c1-93d39a69b025";

export async function cancelSubscriptionService(): Promise<
  SuccessResponse<null> | ErrorResponse
> {
  const subscription =
    await subscriptionRepo.getActiveSubscriptionByTenant(tenantId);

  if (!subscription) {
    return {
      success: false,
      error: {
        code: ERROR_CODES.SUBSCRIPTION_NOT_FOUND,
        message: ERROR_DEFINITIONS[ERROR_CODES.SUBSCRIPTION_NOT_FOUND].message,
        statusCode:
          ERROR_DEFINITIONS[ERROR_CODES.SUBSCRIPTION_NOT_FOUND].statusCode
      }
    };
  }
  if (subscription.cancelAtPeriodEnd) {
    return {
      success: false,
      error: {
        code: ERROR_CODES.SUBSCRIPTION_ALREADY_CANCELED,
        message:
          ERROR_DEFINITIONS[ERROR_CODES.SUBSCRIPTION_ALREADY_CANCELED].message,
        statusCode:
          ERROR_DEFINITIONS[ERROR_CODES.SUBSCRIPTION_ALREADY_CANCELED]
            .statusCode
      }
    };
  }
  if (!subscription.paymentProviderSubscriptionId) {
    return {
      success: false,
      error: {
        code: ERROR_CODES.PAYMENT_PROVIDER_SUBSCRIPTION_NOT_FOUND,
        message:
          ERROR_DEFINITIONS[ERROR_CODES.PAYMENT_PROVIDER_SUBSCRIPTION_NOT_FOUND]
            .message,
        statusCode:
          ERROR_DEFINITIONS[ERROR_CODES.PAYMENT_PROVIDER_SUBSCRIPTION_NOT_FOUND]
            .statusCode
      }
    };
  }

  const updatedSubscription =
    await stripeService.updateSubscriptionCancellation(
      subscription.paymentProviderSubscriptionId,
      true,
      false
    );

  return {
    success: true,
    message: "Subscription cancellation scheduled successfully",
    data: null
  };
}
export async function undoCancelSubscriptionService(): Promise<
  SuccessResponse<null> | ErrorResponse
> {
  const subscription =
    await subscriptionRepo.getActiveSubscriptionByTenant(tenantId);

  if (!subscription) {
    return {
      success: false,
      error: {
        code: ERROR_CODES.SUBSCRIPTION_NOT_FOUND,
        message: ERROR_DEFINITIONS[ERROR_CODES.SUBSCRIPTION_NOT_FOUND].message,
        statusCode:
          ERROR_DEFINITIONS[ERROR_CODES.SUBSCRIPTION_NOT_FOUND].statusCode
      }
    };
  }
  if (!subscription.cancelAtPeriodEnd) {
    return {
      success: false,
      error: {
        code: ERROR_CODES.SUBSCRIPTION_NOT_CANCELED,
        message:
          ERROR_DEFINITIONS[ERROR_CODES.SUBSCRIPTION_NOT_CANCELED].message,
        statusCode:
          ERROR_DEFINITIONS[ERROR_CODES.SUBSCRIPTION_NOT_CANCELED].statusCode
      }
    };
  }
  if (!subscription.paymentProviderSubscriptionId) {
    return {
      success: false,
      error: {
        code: ERROR_CODES.PAYMENT_PROVIDER_SUBSCRIPTION_NOT_FOUND,
        message:
          ERROR_DEFINITIONS[ERROR_CODES.PAYMENT_PROVIDER_SUBSCRIPTION_NOT_FOUND]
            .message,
        statusCode:
          ERROR_DEFINITIONS[ERROR_CODES.PAYMENT_PROVIDER_SUBSCRIPTION_NOT_FOUND]
            .statusCode
      }
    };
  }

  const updatedSubscription =
    await stripeService.updateSubscriptionCancellation(
      subscription.paymentProviderSubscriptionId,
      false,
      false
    );

  return {
    success: true,
    data: null,
    message: "Subscription uncanceled successfully"
  };
}
export async function checkoutService(
  data: {
    planId: UUID;
    promoCode: string;
  },
  userPayload: { email: string }
): Promise<SuccessResponse<{ checkoutUrl: string }> | ErrorResponse> {
  // TODO: replace with authenticated tenant

  // 1. Validate promo code
  console.log("Validating promocode and plan .");

  let validPromoCode = null;
  if (data.promoCode) {
    const validatePromo = await validatePromoCode(data.promoCode, data.planId);

    if (!validatePromo.success) {
      return validatePromo;
    }

    validPromoCode = validatePromo.data as PromoCode;
  }
  console.log("Promocode and plan are valid .");

  // 2. Get plan
  const validPlan = (await plansRepo.getPlanById(data.planId)) as Plan;

  // 3. Check existing ongoing subscription
  console.log("Getting user subscription ");

  const existingSubscription =
    await subscriptionRepo.getSubscriptionByTenant(tenantId);

  if (existingSubscription) {
    return {
      success: false,
      error: {
        code: ERROR_CODES.SUBSCRIPTION_ALREADY_EXISTS,
        message:
          ERROR_DEFINITIONS[ERROR_CODES.SUBSCRIPTION_ALREADY_EXISTS].message,
        statusCode:
          ERROR_DEFINITIONS[ERROR_CODES.SUBSCRIPTION_ALREADY_EXISTS].statusCode
      }
    };
  }
  console.log(
    "User dont have running subscription , craeting new subscription ... "
  );

  console.log("Create stripe's cutomer for the user based on his email ...");
  const testingMode = true;
  // 5. Get/create Stripe customer
  let customer = null;
  if (testingMode) {
    customer = await createCustomerWithClock({
      email: "nas@gmail.com",
      name: "nas",
      testClockId: "clock_1UG62wDvEnSheKucomEewYNM"
    });
  } else {
    customer = await stripeService.createCustomer({
      email: userPayload.email
    });
  }

  console.log("User customer's id registered successfully .", {
    customer: customer.id
  });

  console.log("Creating stripe checkout session ...");

  // 6. Create Stripe Checkout Session
  const session = await stripeService.createCheckoutSession({
    priceId: validPlan.paymentProviderPlanId!,
    customerId: customer.id,
    successUrl: URLS.success,
    cancelUrl: URLS.cancel,
    trialPeriodDays: validPlan.trialPeriodValue,
    couponId: data.promoCode ? validPromoCode?.paymentProviderCoupon : ""
  });

  console.log("Stripe checkout created successfully .");

  // 7. Return Stripe Checkout URL
  return {
    success: true,
    message: "Checkout session created successfully",
    data: {
      checkoutUrl: session.url!
    }
  };
}
