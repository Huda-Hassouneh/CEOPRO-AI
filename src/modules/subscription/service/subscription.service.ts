import { ERROR_CODES } from "../../../errors/error-codes.js";

import plansRepo from "../repo/plans.repo.js";
import subscriptionRepo from "../repo/subscription.repo.js";

import { validatePromoCode } from "./promocodes.service.js";

import { Plan, Subscription } from "../../../generated/prisma/client.js";

import { stripeService } from "../External Services/Payment providers/stripe/stripeService.js";

import { createCustomerWithClock } from "../External Services/Payment providers/stripe/stripe.test-clock.js";

import { BillingOptionType } from "../../../types/plans.js";
import type { CheckoutInput } from "../../../DTO/checkout.dto.js";

/*
 * ============================================================
 * SERVICE RESULT
 * ============================================================
 */

import type { ServiceResult } from "../../../types/service.js";

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
  data: CheckoutInput,
  userPayload: {
    email: string;
    id: string;
    tenant_id: string;
  }
): Promise<ServiceResult<{ checkoutUrl: string }>> {
  // The public request contract uses payment_method. Stripe is the only active
  // payment provider; card/Google Pay are payment methods handled by Stripe Checkout.

  console.log({ te: userPayload.tenant_id });

  if (data.payment_method === "paypal") {
    return {
      success: false,
      code: ERROR_CODES.UNSUPPORTED_PAYMENT_PROVIDER,
      message: "PayPal is not supported by the current payment integration."
    };
  }

  const validPlan = (await plansRepo.getPlanById(data.planId)) as Plan | null;
  if (!validPlan || !validPlan.isActive) {
    return { success: false, code: ERROR_CODES.PLAN_NOT_FOUND };
  }

  // Standard plans are public. Custom plans are private to the tenant that
  // accepted the quote that produced them. Never trust a browser-supplied UUID.
  if (validPlan.planType === "custom" && validPlan.tenantId !== userPayload.tenant_id) {
    return { success: false, code: ERROR_CODES.PLAN_NOT_AVAILABLE };
  }

  let validPromoCode = null;
  if (data.promoCode) {
    const validatePromo = await validatePromoCode(
      data.promoCode,
      data.planId,
      userPayload.tenant_id
    );
    if (!validatePromo.success) return validatePromo;
    validPromoCode = validatePromo.data;
  }

  const existingSubscription =
    await subscriptionRepo.getCurrentSubscriptionByTenant(
      userPayload.tenant_id
    );
  if (existingSubscription) {
    return { success: false, code: ERROR_CODES.SUBSCRIPTION_ALREADY_EXISTS };
  }

  const billingOptions = (validPlan.billingOptions ||
    []) as unknown as BillingOptionType[];
  const selectedPricingOption = billingOptions.find(
    (option) => option.period === data.billing_period
  );
  if (!selectedPricingOption) {
    return {
      success: false,
      code: ERROR_CODES.INVALID_BILLING_PERIOD,
      message: `Billing period '${data.billing_period}' is not available for this plan.`
    };
  }
  if (!selectedPricingOption.stripePriceId) {
    return {
      success: false,
      code: ERROR_CODES.PAYMENT_PROVIDER_ERROR,
      message:
        "The selected billing option does not have a Stripe price configured."
    };
  }

  const testingMode = process.env.STRIPE_USE_TEST_CLOCK === "true";
  let customer;
  if (testingMode) {
    const testClockId = process.env.STRIPE_TEST_CLOCK_ID;
    if (!testClockId) {
      throw new Error(
        "STRIPE_TEST_CLOCK_ID is required when STRIPE_USE_TEST_CLOCK=true"
      );
    }
    customer = await createCustomerWithClock({
      email: userPayload.email,
      name: userPayload.email,
      testClockId,
      metadata: {
        tenantId: userPayload.tenant_id,
        userId: userPayload.id
      }
    });
  } else {
    customer = await stripeService.createCustomer({
      email: userPayload.email,
      userId: userPayload.id,
      tenantId: userPayload.tenant_id
    });
  }

  const session = await stripeService.createCheckoutSession({
    priceId: selectedPricingOption.stripePriceId,
    customerId: customer.id,
    successUrl: URLS.success,
    cancelUrl: URLS.cancel,
    trialPeriodDays: validPlan.trialPeriodValue,
    couponId: data.promoCode
      ? (validPromoCode?.paymentProviderCoupon ?? "")
      : "",
    tenantId: userPayload.tenant_id
  });

  if (!session.url) {
    throw new Error(
      "Stripe Checkout Session was created without a checkout URL."
    );
  }

  return { success: true, data: { checkoutUrl: session.url } };
}
