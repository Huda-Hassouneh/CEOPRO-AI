import Stripe from "stripe";
import type {
  StripePriceDetails,
  StripeService,
  StripeCustomerDetails,
  StripeSubscriptionDetails,
  StripeCheckoutDetails
} from "../../../../../types/Payment Providers/stripe.js";

const STRIPE_SECRET_KEY = process.env.STRIPE_SECRET_KEY;

if (!STRIPE_SECRET_KEY) {
  throw new Error("STRIPE_SECRET_KEY is not configured");
}

export const stripe = new Stripe(STRIPE_SECRET_KEY);

// ============================================================================
// Catalog & Plans
// ============================================================================

export async function createCatalog(
  payload = {
    name: "CEOPRO AI Platform",
    description: "AI-powered business intelligence and advisory platform"
  }
): Promise<Stripe.Product> {
  try {
    return await stripe.products.create({
      name: payload.name,
      description: payload.description,
      metadata: { type: "SERVICE", category: "SOFTWARE" }
    });
  } catch (error) {
    console.error("Stripe create catalog failed:", error);
    throw new Error(
      `Stripe catalog creation failed: ${(error as Error).message}`
    );
  }
}

export async function createPlan(
  productId: string,
  planDetails: StripePriceDetails
): Promise<Stripe.Price> {
  if (!productId) throw new Error("Stripe product ID is required");

  const {
    name,
    description,
    unitAmount,
    currency,
    interval,
    intervalCount,
    trialPeriodDays
  } = planDetails;

  try {
    return await stripe.prices.create({
      product: productId,
      nickname: name,
      currency: currency.toLowerCase(),
      unit_amount: Math.round(unitAmount * 100), // cents
      recurring: {
        interval,
        interval_count: intervalCount ?? 1
      },
      ...(trialPeriodDays ? { trial_period_days: trialPeriodDays } : {}),
      metadata: description ? { description } : undefined
    });
  } catch (error) {
    console.error("Stripe price creation failed:", error);
    throw new Error(
      `Stripe price creation failed: ${(error as Error).message}`
    );
  }
}

export async function stripeOnBoarding(): Promise<Stripe.Product> {
  return createCatalog();
}

// ============================================================================
// Customers
// ============================================================================

export async function createCustomer(
  details: StripeCustomerDetails
): Promise<Stripe.Customer> {
  const { email, name, userId } = details;

  try {
    const existing = await stripe.customers.list({ email, limit: 1 });

    if (existing.data.length > 0) {
      console.log("RETURNING EXISTING CUSTOMER ....");
      return existing.data[0];
    }

    return await stripe.customers.create({
      email,
      name,
      metadata: userId ? { userId } : undefined
    });
  } catch (error) {
    console.error("Stripe customer creation failed:", error);
    throw new Error(
      `Stripe customer creation failed: ${(error as Error).message}`
    );
  }
}

export async function deleteCustomerByCustomerId(
  customerId: string
): Promise<boolean> {
  if (!customerId) throw new Error("Stripe Customer ID is required");

  try {
    await stripe.customers.del(customerId);
    return true;
  } catch (error) {
    console.error("Customer deletion failed:", error);
    throw new Error(`Customer deletion failed: ${(error as Error).message}`);
  }
}

export async function createCustomerPortalSession(
  customerId: string,
  returnUrl: string
): Promise<string> {
  const portalSession = await stripe.billingPortal.sessions.create({
    customer: customerId,
    return_url: returnUrl
  });
  return portalSession.url;
}

// ============================================================================
// Checkout & Subscriptions
// ============================================================================

export async function createPromoCode(
  type: string,
  amount: number,
  discountAppliedFor: string = "once",
  currency: string = "usd"
): Promise<Stripe.Coupon> {
  if (amount <= 0) throw new Error("Discount amount must be greater than 0");
  if (type === "percentage" && amount > 100)
    throw new Error("Percentage discount cannot exceed 100%");

  return await stripe.coupons.create(
    type === "percentage"
      ? { percent_off: amount, currency, duration: discountAppliedFor }
      : { amount_off: amount, currency, duration: discountAppliedFor }
  );
}

export async function createCheckoutSession(
  details: StripeCheckoutDetails
): Promise<Stripe.Checkout.Session> {
  const {
    priceId,
    customerId,
    customerEmail,
    successUrl,
    cancelUrl,
    trialPeriodDays,
    couponId,
    tenantId
  } = details;

  try {
    return await stripe.checkout.sessions.create({
      mode: "subscription",
      line_items: [{ price: priceId, quantity: 1 }],
      customer: customerId,
      customer_email: customerId ? undefined : customerEmail,
      success_url: successUrl,
      cancel_url: cancelUrl,
      client_reference_id: tenantId,
      metadata: { tenantId },
      subscription_data: {
        metadata: { tenantId },
        ...(trialPeriodDays ? { trial_period_days: trialPeriodDays } : {})
      },
      ...(couponId ? { discounts: [{ coupon: couponId }] } : {})
    });
  } catch (error) {
    console.error("Stripe checkout session creation failed:", error);
    throw new Error(
      `Stripe checkout session creation failed: ${(error as Error).message}`
    );
  }
}

export async function createSubscription(
  details: StripeSubscriptionDetails
): Promise<Stripe.Subscription> {
  const { customerId, priceId, trialPeriodDays } = details;

  try {
    return await stripe.subscriptions.create({
      customer: customerId,
      items: [{ price: priceId }],
      ...(trialPeriodDays ? { trial_period_days: trialPeriodDays } : {}),
      collection_method: "charge_automatically"
    });
  } catch (error) {
    console.error("Stripe subscription creation failed:", error);
    throw new Error(
      `Stripe subscription creation failed: ${(error as Error).message}`
    );
  }
}

export async function retrieveSubscription(
  subscriptionId: string
): Promise<Stripe.Subscription> {
  return await stripe.subscriptions.retrieve(subscriptionId);
}

export async function updateSubscription(data: {
  paymentProviderSubscriptionId: string;
  stripeSubscriptionItemId: string;
  paymentProviderPriceId: string;
  action: "upgrade" | "downgrade";
}): Promise<Stripe.Subscription> {
  const {
    paymentProviderSubscriptionId,
    stripeSubscriptionItemId,
    paymentProviderPriceId,
    action
  } = data;

  const subscription = await stripe.subscriptions.retrieve(
    paymentProviderSubscriptionId
  );

  if (action === "upgrade") {
    // Releasing pending downgrade schedule if it exists
    if (subscription.schedule) {
      console.log(
        `Releasing schedule ${subscription.schedule} to allow upgrade.`
      );
      await stripe.subscriptionSchedules.release(
        subscription.schedule as string
      );
    }

    return await stripe.subscriptions.update(paymentProviderSubscriptionId, {
      items: [{ id: stripeSubscriptionItemId, price: paymentProviderPriceId }],
      proration_behavior: "create_prorations"
    });
  }

  // DOWNGRADE: Schedule for end of billing cycle
  let scheduleId = subscription.schedule as string | null;

  if (!scheduleId) {
    const schedule = await stripe.subscriptionSchedules.create({
      from_subscription: paymentProviderSubscriptionId
    });
    scheduleId = schedule.id;
  }

  const schedule = await stripe.subscriptionSchedules.retrieve(scheduleId);
  const currentPhase = schedule.phases[0];

  await stripe.subscriptionSchedules.update(scheduleId, {
    end_behavior: "release",
    phases: [
      {
        start_date: currentPhase.start_date,
        end_date: currentPhase.end_date,
        items: currentPhase.items.map((item) => ({
          price: typeof item.price === "string" ? item.price : item.price.id,
          quantity: item.quantity
        }))
      },
      {
        items: [{ price: paymentProviderPriceId, quantity: 1 }]
      }
    ]
  });

  return await stripe.subscriptions.retrieve(paymentProviderSubscriptionId);
}

export async function updateSubscriptionCancellation(
  subscriptionId: string,
  cancelAtPeriodEnds: boolean,
  deleteImmediately: boolean // Typo fixed from deleteImmedietly
): Promise<Stripe.Subscription> {
  const subscription = await stripe.subscriptions.retrieve(subscriptionId);

  if (subscription.schedule) {
    console.log(
      `Releasing schedule ${subscription.schedule} to allow cancellation update.`
    );
    await stripe.subscriptionSchedules.release(subscription.schedule as string);
  }

  if (deleteImmediately) {
    return await stripe.subscriptions.cancel(subscriptionId);
  }

  return await stripe.subscriptions.update(subscriptionId, {
    cancel_at_period_end: cancelAtPeriodEnds
  });
}

// ============================================================================
// Service Export
// ============================================================================

export const stripeService: StripeService = {
  createCatalog,
  createPlan,
  stripeOnBoarding,
  createCustomer,
  createSubscription,
  createCheckoutSession,
  createPromoCode,
  updateSubscription,
  retrieveSubscription,
  updateSubscriptionCancellation,
  deleteCustomerByCustomerId,
  createCustomerPortalSession,
  stripe
};
