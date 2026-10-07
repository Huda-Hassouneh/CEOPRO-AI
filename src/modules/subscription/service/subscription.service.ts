import { ERROR_CODES } from "../../../errors/error-codes.js";

import plansRepo from "../repo/plans.repo.js";
import subscriptionRepo from "../repo/subscription.repo.js";

import { validatePromoCode } from "./promocodes.service.js";

import { CurrentSubscriptionResponse } from "../types/subscription.types.js";

import { stripeService } from "../client/payment-providers/stripe/stripe.client.js";

import { createCustomerWithClock } from "../client/payment-providers/stripe/stripe.test-clock.js";

import { BillingOptionType } from "../types/plans.types.js";
import type { CheckoutInput } from "../types/checkout.dto.js";
import {
  isRecoverableSubscriptionStatus,
  type SubscriptionRecoveryData
} from "../types/subscription-recovery.types.js";

/*
 * ============================================================
 * SERVICE RESULT
 * ============================================================
 */

import type { ServiceResult } from "../../../types/service.js";
import { Plan } from "../../../generated/prisma/client.js";

/*
 * ============================================================
 * URLS
 * ============================================================
 */

const URLS = {
  success: process.env.SUCCESS_SUBSCRIPTION_URL || "http://localhost:5173",

  cancel: process.env.FAILED_SUBSCRIPTION_URL || "http://localhost:5173"
};

function getSubscriptionRecoveryReturnUrl(): string {
  const configured = process.env.SUBSCRIPTION_RECOVERY_RETURN_URL?.trim();
  if (configured) {
    return configured;
  }

  try {
    const successUrl = new URL(URLS.success);
    return new URL("/billing", successUrl.origin).toString();
  } catch {
    return "http://localhost:5173/billing";
  }
}

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
): Promise<ServiceResult<CurrentSubscriptionResponse>> {
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

  const version = subscription.paymentProviderPriceId
    ? await plansRepo.getPriceVersionByStripeId(
        subscription.paymentProviderPriceId
      )
    : null;

  return {
    success: true,
    data: {
      ...subscription,
      currentPrice:
        version && version.planId === subscription.planId
          ? {
              amount: version.amount,
              currency: version.currency,
              intervalUnit: version.intervalUnit,
              intervalCount: version.intervalCount,
              period: version.periodCode
            }
          : null
    }
  };
}

/*
 * ============================================================
 * SUBSCRIPTION PAYMENT RECOVERY
 * ============================================================
 *
 * Recover the EXISTING Stripe subscription. Never create a second
 * subscription for pending / past_due / payment_failed / paused states.
 *
 * Preferred recovery:
 *   - pending -> latest open invoice -> Complete payment
 *   - past_due / payment_failed -> latest open invoice -> Resolve payment
 *   - paused -> Stripe Customer Portal
 *   - invoice URL unavailable -> Stripe Customer Portal fallback
 *
 * Stripe/webhooks remain authoritative for the final subscription state.
 */
export async function createSubscriptionRecoveryService(
  tenantId: string
): Promise<ServiceResult<SubscriptionRecoveryData>> {
  const subscription =
    await subscriptionRepo.getCurrentSubscriptionByTenant(tenantId);

  if (!subscription) {
    return {
      success: false,
      code: ERROR_CODES.SUBSCRIPTION_NOT_FOUND
    };
  }

  if (!isRecoverableSubscriptionStatus(subscription.status)) {
    return {
      success: false,
      code: ERROR_CODES.INVALID_SUBSCRIPTION_STATUS,
      message: "This subscription does not require payment recovery."
    };
  }

  if (subscription.paymentProvider.toLowerCase() !== "stripe") {
    return {
      success: false,
      code: ERROR_CODES.UNSUPPORTED_PAYMENT_PROVIDER,
      message: "Payment recovery is not available for this payment provider."
    };
  }

  if (!subscription.paymentProviderSubscriptionId) {
    return {
      success: false,
      code: ERROR_CODES.PAYMENT_PROVIDER_SUBSCRIPTION_NOT_FOUND
    };
  }

  try {
    const providerSubscription =
      await stripeService.retrieveSubscriptionForRecovery(
        subscription.paymentProviderSubscriptionId
      );

    /*
     * Defense in depth for multi-tenant recovery. A Stripe subscription created
     * before tenant metadata was introduced may have no tenantId, so absence is
     * allowed. A conflicting tenantId is never allowed.
     */
    if (
      providerSubscription.tenantId &&
      providerSubscription.tenantId !== tenantId
    ) {
      console.error("Stripe subscription recovery tenant mismatch", {
        tenantId,
        providerSubscriptionId: providerSubscription.subscriptionId
      });

      return {
        success: false,
        code: ERROR_CODES.PAYMENT_PROVIDER_ERROR,
        message: "The payment-provider subscription could not be verified."
      };
    }

    if (
      subscription.paymentProviderCustomerId &&
      providerSubscription.customerId &&
      subscription.paymentProviderCustomerId !== providerSubscription.customerId
    ) {
      console.error("Stripe subscription recovery customer mismatch", {
        tenantId,
        providerSubscriptionId: providerSubscription.subscriptionId
      });

      return {
        success: false,
        code: ERROR_CODES.PAYMENT_PROVIDER_ERROR,
        message: "The payment-provider customer could not be verified."
      };
    }

    const invoice = providerSubscription.latestInvoice;
    const hasPayableInvoice =
      invoice?.status === "open" && Boolean(invoice.hostedInvoiceUrl);

    if (
      subscription.status !== "paused" &&
      hasPayableInvoice &&
      invoice?.hostedInvoiceUrl
    ) {
      return {
        success: true,
        data: {
          type:
            subscription.status === "pending"
              ? "complete_payment"
              : "resolve_payment",
          url: invoice.hostedInvoiceUrl
        }
      };
    }

    const customerId =
      subscription.paymentProviderCustomerId ?? providerSubscription.customerId;

    if (!customerId) {
      return {
        success: false,
        code: ERROR_CODES.PAYMENT_PROVIDER_ERROR,
        message:
          "Payment recovery is unavailable because the Stripe customer is missing."
      };
    }

    const portalUrl = await stripeService.createCustomerPortalSession(
      customerId,
      getSubscriptionRecoveryReturnUrl()
    );

    return {
      success: true,
      data: {
        type: "manage_billing",
        url: portalUrl
      }
    };
  } catch (error) {
    console.error("Subscription payment recovery failed:", error);

    return {
      success: false,
      code: ERROR_CODES.PAYMENT_PROVIDER_ERROR,
      message:
        "We could not start subscription payment recovery. Please try again."
    };
  }
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
  if (
    validPlan.planType === "custom" &&
    validPlan.tenantId !== userPayload.tenant_id
  ) {
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
/*
 * ============================================================
 * CANCEL SCHEDULED PLAN CHANGE
 * ============================================================
 *
 * Cancels ONLY a future scheduled plan change/downgrade.
 *
 * Important:
 * - Does NOT cancel the subscription.
 * - Does NOT change the current plan.
 * - Does NOT change the current billing period.
 * - Releases the Stripe Subscription Schedule first.
 * - Clears local scheduled fields only after Stripe confirms
 *   that the schedule is no longer attached.
 */
export async function cancelScheduledPlanChangeService(
  tenantId: string
): Promise<ServiceResult<null>> {
  /*
   * 1. Load the current subscription for this tenant.
   *
   * Use getCurrentSubscriptionByTenant(), not the access-only
   * subscription query.
   */
  const subscription =
    await subscriptionRepo.getCurrentSubscriptionByTenant(tenantId);

  if (!subscription) {
    return {
      success: false,
      code: ERROR_CODES.SUBSCRIPTION_NOT_FOUND
    };
  }

  /*
   * 2. Make sure CEOPRO actually knows about a scheduled
   *    future plan change.
   *
   * Normally both fields should exist together, but checking
   * both makes this safe if historical data is incomplete.
   */
  const hasScheduledPlanChange =
    Boolean(subscription.scheduledPlanId) ||
    Boolean(subscription.scheduledBillingPeriod);

  if (!hasScheduledPlanChange) {
    return {
      success: false,
      code: ERROR_CODES.NO_SCHEDULED_PLAN_CHANGE,
      message: "There is no scheduled plan change to cancel."
    };
  }

  /*
   * 3. This operation currently relies on Stripe Subscription
   *    Schedules.
   */
  if (subscription.paymentProvider.toLowerCase() !== "stripe") {
    return {
      success: false,
      code: ERROR_CODES.UNSUPPORTED_PAYMENT_PROVIDER,
      message:
        "Cancelling a scheduled plan change is not available for this payment provider."
    };
  }

  /*
   * 4. We need the real Stripe subscription ID.
   *
   * Never accept this ID from the frontend. It must come from
   * the tenant-scoped subscription row.
   */
  if (!subscription.paymentProviderSubscriptionId) {
    return {
      success: false,
      code: ERROR_CODES.PAYMENT_PROVIDER_SUBSCRIPTION_NOT_FOUND
    };
  }

  try {
    /*
     * 5. Release the Subscription Schedule in Stripe FIRST.
     *
     * releaseSubscriptionSchedule() should:
     *
     * - retrieve the Stripe subscription;
     * - find subscription.schedule;
     * - release it using preserve_cancel_date: true;
     * - retrieve the subscription again;
     * - return the refreshed Stripe subscription.
     *
     * This keeps Stripe authoritative.
     */
    const providerSubscription =
      await stripeService.releaseSubscriptionSchedule(
        subscription.paymentProviderSubscriptionId
      );

    /*
     * 6. Provider confirmation.
     *
     * If Stripe still says a schedule is attached, DO NOT
     * clear CEOPRO's scheduledPlanId/scheduledBillingPeriod.
     *
     * Otherwise CEOPRO would claim that the downgrade was
     * cancelled while Stripe still intends to perform it.
     */
    if (providerSubscription.schedule) {
      return {
        success: false,
        code: ERROR_CODES.PAYMENT_PROVIDER_ERROR,
        message:
          "The scheduled plan change could not be released by the payment provider."
      };
    }

    /*
     * 7. Stripe has confirmed the future schedule is gone.
     *
     * Now clear only CEOPRO's future-plan metadata.
     *
     * DO NOT modify:
     *
     * - planId
     * - billingPeriod
     * - paymentProviderPriceId
     * - cancelAtPeriodEnd
     *
     * The customer simply stays on the current plan.
     */
    await subscriptionRepo.updateSubscription(subscription.id, {
      scheduledPlanId: null,
      scheduledBillingPeriod: null
    });

    return {
      success: true,
      data: null
    };
  } catch (error) {
    /*
     * 8. Most importantly:
     *
     * if Stripe fails, the local scheduled fields remain
     * untouched.
     */
    console.error("Cancel scheduled plan change failed:", {
      tenantId,
      subscriptionId: subscription.id,
      error
    });

    return {
      success: false,
      code: ERROR_CODES.PAYMENT_PROVIDER_ERROR,
      message:
        "The scheduled plan change could not be cancelled. Please try again."
    };
  }
}
