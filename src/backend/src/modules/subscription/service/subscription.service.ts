import { ERROR_CODES } from "../../../errors/error-codes.js";

import plansRepo from "../repo/plans.repo.js";
import subscriptionRepo from "../repo/subscription.repo.js";

import { validatePromoCode } from "./promocodes.service.js";

import { Plan, Subscription } from "../../../generated/prisma/client.js";

import { UUID } from "node:crypto";

import { stripeService } from "../External Services/Payment providers/stripe/stripeService.js";

import { createCustomerWithClock } from "../External Services/Payment providers/stripe/stripe.test-clock.js";

import { BillingOptionType } from "../../../types/plans.js";

/*
 * ============================================================
 * SERVICE RESULT
 * ============================================================
 */

export type ServiceResult<T> =
  | {
      success: true;
      data: T;
    }
  | {
      success: false;
      code: string;
      message?: string;
    };

/*
 * ============================================================
 * URLS
 * ============================================================
 */

const URLS = {
  success: process.env.SUCCESS_SUBSCRIPTION_URL || "http://localhost:5173",

  cancel: process.env.FAILED_SUBSCRIPTION_URL || "http://localhost:5173"
};

/*
 * ============================================================
 * CANCEL SUBSCRIPTION
 * ============================================================
 */

export async function cancelSubscriptionService(
  tenantId: string
): Promise<ServiceResult<null>> {
  /*
   * IMPORTANT:
   *
   * Use CURRENT subscription, not only "active".
   *
   * A trialing tenant must also be able to cancel.
   *
   * A past_due subscription also still exists in Stripe and
   * may need to be cancelled.
   */
  const subscription =
    await subscriptionRepo.getCurrentSubscriptionByTenant(tenantId);

  if (!subscription) {
    return {
      success: false,
      code: ERROR_CODES.SUBSCRIPTION_NOT_FOUND
    };
  }

  if (subscription.cancelAtPeriodEnd) {
    return {
      success: false,
      code: ERROR_CODES.SUBSCRIPTION_ALREADY_CANCELED
    };
  }

  if (!subscription.paymentProviderSubscriptionId) {
    return {
      success: false,
      code: ERROR_CODES.PAYMENT_PROVIDER_SUBSCRIPTION_NOT_FOUND
    };
  }

  /*
   * Stripe remains the source of truth.
   *
   * We DON'T manually modify our local subscription here.
   *
   * customer.subscription.updated will synchronize:
   *
   * cancelAtPeriodEnd = true
   */
  await stripeService.updateSubscriptionCancellation(
    subscription.paymentProviderSubscriptionId,
    true,
    false
  );

  return {
    success: true,
    data: null
  };
}

/*
 * ============================================================
 * UNDO SUBSCRIPTION CANCELLATION
 * ============================================================
 */

export async function undoCancelSubscriptionService(
  tenantId: string
): Promise<ServiceResult<null>> {
  const subscription =
    await subscriptionRepo.getCurrentSubscriptionByTenant(tenantId);

  if (!subscription) {
    return {
      success: false,
      code: ERROR_CODES.SUBSCRIPTION_NOT_FOUND
    };
  }

  if (!subscription.cancelAtPeriodEnd) {
    return {
      success: false,
      code: ERROR_CODES.SUBSCRIPTION_NOT_CANCELED
    };
  }

  if (!subscription.paymentProviderSubscriptionId) {
    return {
      success: false,
      code: ERROR_CODES.PAYMENT_PROVIDER_SUBSCRIPTION_NOT_FOUND
    };
  }

  await stripeService.updateSubscriptionCancellation(
    subscription.paymentProviderSubscriptionId,
    false,
    false
  );

  /*
   * Again:
   *
   * customer.subscription.updated
   *
   * will synchronize local DB state.
   */
  return {
    success: true,
    data: null
  };
}

/*
 * ============================================================
 * GET CURRENT SUBSCRIPTION
 * ============================================================
 */

export async function getCurrentSubscriptionService(
  tenantId: string
): Promise<ServiceResult<Subscription>> {
  const subscription =
    await subscriptionRepo.getCurrentSubscriptionByTenant(tenantId);

  if (!subscription) {
    return {
      success: false,
      code: ERROR_CODES.SUBSCRIPTION_NOT_FOUND
    };
  }

  if (!subscription.paymentProviderSubscriptionId) {
    return {
      success: false,
      code: ERROR_CODES.PAYMENT_PROVIDER_SUBSCRIPTION_NOT_FOUND
    };
  }

  return {
    success: true,
    data: subscription
  };
}

/*
 * ============================================================
 * CHECKOUT
 * ============================================================
 */

export async function checkoutService(
  data: {
    planId: UUID;
    promoCode: string;
    billing_period: string;
    payment_provider: string;
  },

  userPayload: {
    email: string;
    id: string;
    tenant_id: string;
  }
): Promise<
  ServiceResult<{
    checkoutUrl: string;
  }>
> {
  /*
   * ========================================================
   * 1. PAYMENT PROVIDER VALIDATION
   * ========================================================
   *
   * Right now this implementation supports Stripe only.
   */

  if (data.payment_provider && data.payment_provider !== "stripe") {
    return {
      success: false,
      code: "UNSUPPORTED_PAYMENT_PROVIDER",
      message: `Unsupported payment provider: ${data.payment_provider}`
    };
  }

  /*
   * ========================================================
   * 2. VALIDATE PLAN
   * ========================================================
   */

  console.log("[Subscription] Validating plan...");

  const validPlan = (await plansRepo.getPlanById(data.planId)) as Plan | null;

  if (!validPlan) {
    return {
      success: false,
      code: "PLAN_NOT_FOUND",
      message: "The selected subscription plan does not exist."
    };
  }

  /*
   * ========================================================
   * 3. VALIDATE PROMO CODE
   * ========================================================
   */

  let validPromoCode = null;

  if (data.promoCode) {
    console.log("[Subscription] Validating promo code...");

    const validatePromo = await validatePromoCode(data.promoCode, data.planId);

    if (!validatePromo.success) {
      return validatePromo;
    }

    validPromoCode = validatePromo.data;
  }

  /*
   * ========================================================
   * 4. CHECK FOR EXISTING CURRENT SUBSCRIPTION
   * ========================================================
   *
   * This is a critical change.
   *
   * We block:
   *
   * trialing
   * active
   * past_due
   * pending
   * payment_failed
   * paused
   *
   * We DO NOT block:
   *
   * cancelled
   * expired
   */

  console.log("[Subscription] Checking tenant subscription...", {
    tenantId: userPayload.tenant_id
  });

  const existingSubscription =
    await subscriptionRepo.getCurrentSubscriptionByTenant(
      userPayload.tenant_id
    );

  if (existingSubscription) {
    return {
      success: false,
      code: ERROR_CODES.SUBSCRIPTION_ALREADY_EXISTS
    };
  }

  /*
   * ========================================================
   * 5. BILLING OPTION VALIDATION
   * ========================================================
   */

  const billingOptions = (validPlan.billingOptions ||
    []) as unknown as BillingOptionType[];

  const selectedPricingOption = billingOptions.find(
    (option) => option.period === data.billing_period
  );

  if (!selectedPricingOption) {
    return {
      success: false,
      code: "INVALID_BILLING_PERIOD",
      message:
        `Billing period '${data.billing_period}' ` +
        `is not available for this plan.`
    };
  }

  if (!selectedPricingOption.stripePriceId) {
    return {
      success: false,
      code: "STRIPE_PRICE_NOT_CONFIGURED",
      message:
        "The selected billing option does not have a Stripe price configured."
    };
  }

  /*
   * ========================================================
   * 6. STRIPE TEST CLOCK CONFIGURATION
   * ========================================================
   *
   * OLD:
   *
   * const testingMode = true;
   *
   * That must not remain hardcoded.
   */

  const testingMode = process.env.STRIPE_USE_TEST_CLOCK === "true";

  let customer;

  /*
   * ========================================================
   * 7. CREATE STRIPE CUSTOMER
   * ========================================================
   */

  if (testingMode) {
    const testClockId = process.env.STRIPE_TEST_CLOCK_ID;

    if (!testClockId) {
      throw new Error(
        "STRIPE_TEST_CLOCK_ID is required when " + "STRIPE_USE_TEST_CLOCK=true"
      );
    }

    console.log("[Subscription] Creating Stripe test-clock customer...");

    customer = await createCustomerWithClock({
      email: userPayload.email,
      name: userPayload.email,
      testClockId
    });
  } else {
    console.log("[Subscription] Creating Stripe customer...");

    /*
     * Kept compatible with your existing createCustomer()
     * method.
     *
     * If your Stripe wrapper supports customer metadata,
     * I recommend also storing:
     *
     * metadata: {
     *   tenantId: userPayload.tenant_id
     * }
     */
    customer = await stripeService.createCustomer({
      email: userPayload.email
    });
  }

  console.log("[Subscription] Stripe customer created.", {
    customerId: customer.id
  });

  /*
   * ========================================================
   * 8. CREATE CHECKOUT SESSION
   * ========================================================
   */

  console.log("[Subscription] Creating Stripe Checkout session...");

  const session = await stripeService.createCheckoutSession({
    priceId: selectedPricingOption.stripePriceId,

    customerId: customer.id,

    successUrl: URLS.success,

    cancelUrl: URLS.cancel,

    trialPeriodDays: validPlan.trialPeriodValue,

    couponId: data.promoCode
      ? (validPromoCode?.paymentProviderCoupon ?? "")
      : "",

    /*
     * VERY IMPORTANT:
     *
     * Your Stripe createCheckoutSession() implementation
     * should put this tenantId on:
     *
     * 1. Checkout Session metadata
     *
     * AND
     *
     * 2. subscription_data.metadata
     *
     * So customer.subscription.created can resolve the
     * tenant even if it arrives before
     * checkout.session.completed.
     */
    tenantId: userPayload.tenant_id
  });

  /*
   * Stripe Checkout should normally return a URL for a
   * hosted checkout Session.
   */
  if (!session.url) {
    throw new Error(
      "Stripe Checkout Session was created without a checkout URL."
    );
  }

  console.log("[Subscription] Stripe Checkout session created successfully.", {
    sessionId: session.id
  });

  /*
   * ========================================================
   * 9. RETURN CHECKOUT URL
   * ========================================================
   */

  return {
    success: true,

    data: {
      checkoutUrl: session.url
    }
  };
}
