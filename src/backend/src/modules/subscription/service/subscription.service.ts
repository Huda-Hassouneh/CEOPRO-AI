import { ERROR_CODES } from "../../../errors/error-codes.js";
import plansRepo from "../repo/plans.repo.js";
import subscriptionRepo from "../repo/subscription.repo.js";
import { validatePromoCode } from "./promocodes.service.js";
import { Plan, Subscription } from "../../../generated/prisma/client.js";
import { UUID } from "node:crypto";
import { stripeService } from "../External Services/Payment providers/stripe/stripeService.js";
import { createCustomerWithClock } from "../External Services/Payment providers/stripe/stripe.test-clock.js";
import { BillingOptionType } from "../../../types/plans.js";

// A clean domain result without HTTP types
export type ServiceResult<T> =
  | { success: true; data: T }
  | { success: false; code: string; message?: string };

const URLS = {
  success: process.env.SUCCESS_SUBSCRIPTION_URL || "http://localhost:5173",
  cancel: process.env.FAILED_SUBSCRIPTION_URL || "http://localhost:5173"
};
// const tenantId =
//   process.env.MOCK_TENANT_ID || "1b75a922-162b-4d02-ab9a-3c6b36c7e2a7";

export async function cancelSubscriptionService(
  tenantId: string
): Promise<ServiceResult<null>> {
  const subscription =
    await subscriptionRepo.getActiveSubscriptionByTenant(tenantId);

  if (!subscription) {
    return { success: false, code: ERROR_CODES.SUBSCRIPTION_NOT_FOUND };
  }

  if (subscription.cancelAtPeriodEnd) {
    return { success: false, code: ERROR_CODES.SUBSCRIPTION_ALREADY_CANCELED };
  }

  if (!subscription.paymentProviderSubscriptionId) {
    return {
      success: false,
      code: ERROR_CODES.PAYMENT_PROVIDER_SUBSCRIPTION_NOT_FOUND
    };
  }

  await stripeService.updateSubscriptionCancellation(
    subscription.paymentProviderSubscriptionId,
    true,
    false
  );

  return { success: true, data: null };
}

export async function undoCancelSubscriptionService(
  tenantId: string
): Promise<ServiceResult<null>> {
  const subscription =
    await subscriptionRepo.getActiveSubscriptionByTenant(tenantId);

  if (!subscription) {
    return { success: false, code: ERROR_CODES.SUBSCRIPTION_NOT_FOUND };
  }

  if (!subscription.cancelAtPeriodEnd) {
    return { success: false, code: ERROR_CODES.SUBSCRIPTION_NOT_CANCELED };
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

  return { success: true, data: null };
}
export async function getCurrentSubscriptionService(
  tenantId: string
): Promise<ServiceResult<Subscription>> {
  const subscription =
    await subscriptionRepo.getActiveSubscriptionByTenant(tenantId);

  if (!subscription) {
    return { success: false, code: ERROR_CODES.SUBSCRIPTION_NOT_FOUND };
  }

  if (!subscription.paymentProviderSubscriptionId) {
    return {
      success: false,
      code: ERROR_CODES.PAYMENT_PROVIDER_SUBSCRIPTION_NOT_FOUND
    };
  }

  return { success: true, data: subscription };
}
export async function checkoutService(
  data: {
    planId: UUID;
    promoCode: string;
    billing_period: string;
    payment_provider: string;
  },
  userPayload: { email: string; id: string; tenant_id: string }
): Promise<ServiceResult<{ checkoutUrl: string }>> {
  // 1. Validate promo code
  console.log("Validating promocode and plan.");

  let validPromoCode = null;
  if (data.promoCode) {
    const validatePromo = await validatePromoCode(data.promoCode, data.planId);

    // If promo code is invalid, just pass the error result right back up to the controller
    if (!validatePromo.success) {
      return validatePromo;
    }

    validPromoCode = validatePromo.data;
  }
  console.log("Promocode and plan are valid.");

  // 2. Get plan
  const validPlan = (await plansRepo.getPlanById(data.planId)) as Plan;

  // 3. Check existing ongoing subscription
  console.log("Getting user subscription");
  console.log("Subscription tenant_id:", userPayload.tenant_id);
  const existingSubscription = await subscriptionRepo.getSubscriptionByTenant(
    userPayload.tenant_id
  );
  console.log({ tenantid: userPayload.tenant_id });

  if (existingSubscription) {
    return { success: false, code: ERROR_CODES.SUBSCRIPTION_ALREADY_EXISTS };
  }

  console.log(
    "User doesn't have a running subscription, creating new subscription..."
  );
  console.log("Create stripe customer for the user based on their email...");

  const testingMode = true;

  // 5. Get/create Stripe customer
  let customer = null;
  if (testingMode) {
    customer = await createCustomerWithClock({
      email: userPayload.email,
      name: userPayload.email,
      testClockId: "clock_1UHX7QDvEnSheKucdpTmyU5Z"
    });
  } else {
    customer = await stripeService.createCustomer({
      email: userPayload.email
    });
  }

  console.log("User customer's id registered successfully.", {
    customer: customer.id
  });
  console.log("Creating stripe checkout session...");

  // 1. Safely extract and cast the Prisma JSON to your array type
  const billingOptions = (validPlan?.billingOptions ||
    []) as unknown as BillingOptionType[];

  // 2. Now you can safely use array methods like .find()
  const selectedPricingOption = billingOptions.find(
    (option) => option.period === data.billing_period
  );

  if (!selectedPricingOption) {
    // Handle the error if they send a period that doesn't exist on this plan
    throw new Error(
      `Billing period '${data.billing_period}' is not available for this plan.`
    );
  }
  // 6. Create Stripe Checkout Session
  const session = await stripeService.createCheckoutSession({
    priceId: selectedPricingOption.stripePriceId as string,
    customerId: customer.id,
    successUrl: URLS.success,
    cancelUrl: URLS.cancel,
    trialPeriodDays: validPlan.trialPeriodValue,
    couponId: data.promoCode ? validPromoCode?.paymentProviderCoupon : "",
    tenantId: userPayload.tenant_id
  });

  console.log("Stripe checkout created successfully.");

  // 7. Return Stripe Checkout URL
  return {
    success: true,
    data: { checkoutUrl: session.url! }
  };
}
