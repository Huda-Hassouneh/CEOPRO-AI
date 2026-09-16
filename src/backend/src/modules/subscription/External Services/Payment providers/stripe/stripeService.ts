import Stripe from "stripe";

import type {
  StripePriceDetails,
  StripeService,
  StripeCustomerDetails,
  StripeSubscriptionDetails,
  StripeCheckoutDetails
} from "../../../../../types/Payment Providers/stripe.js";

// Helper: Safely resolve Subscription ID across Stripe API versions

const STRIPE_SECRET_KEY = process.env.STRIPE_SECRET_KEY;

if (!STRIPE_SECRET_KEY) {
  throw new Error("STRIPE_SECRET_KEY is not configured");
}

const stripe = new Stripe(STRIPE_SECRET_KEY);

export async function createPromoCode(
  type: string,
  amount: number
): Promise<Stripe.Coupon> {
  if (amount <= 0) {
    throw new Error("Discount amount must be greater than 0");
  }

  if (type === "percentage" && amount > 100) {
    throw new Error("Percentage discount cannot exceed 100%");
  }

  const coupon = await stripe.coupons.create(
    type === "percentage"
      ? {
          percent_off: amount,
          duration: "forever"
        }
      : {
          amount_off: amount,
          currency: "usd",
          duration: "forever"
        }
  );

  return coupon;
}
// Creates the CEOPRO AI Platform product in the Stripe catalog.
async function createCatalog(
  payload = {
    name: "CEOPRO AI Platform",
    description: "AI-powered business intelligence and advisory platform"
  }
): Promise<Stripe.Product> {
  try {
    const product = await stripe.products.create({
      name: payload.name,
      description: payload.description,
      metadata: { type: "SERVICE", category: "SOFTWARE" }
    });

    return product;
  } catch (error) {
    console.error("Stripe create catalog failed:", error);
    throw new Error(
      `Stripe catalog creation failed: ${(error as Error).message}`
    );
  }
}

// Creates a Stripe price (recurring) attached to the CEOPRO product.
async function createPlan(
  productId: string,
  planDetails: StripePriceDetails
): Promise<Stripe.Price> {
  if (!productId) {
    throw new Error("Stripe product ID is required");
  }

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
    const price = await stripe.prices.create({
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

    return price;
  } catch (error) {
    console.error("Stripe price creation failed:", error);
    throw new Error(
      `Stripe price creation failed: ${(error as Error).message}`
    );
  }
}
// Delete customer based on its id
async function deleteCustomerByCustomerId(
  customerId: string
): Promise<boolean> {
  if (!customerId) {
    throw new Error("Stripe Customer ID is required");
  }

  try {
    await stripe.customers.del(customerId);
    return true;
  } catch (error) {
    console.error("Customer deletion failed:", error);
    throw new Error(`Customer deletion failed: ${(error as Error).message}`);
  }
}

// Performs the one-time Stripe onboarding setup for CEOPRO.
async function stripeOnBoarding(): Promise<Stripe.Product> {
  return createCatalog();
}

// Finds an existing Stripe customer by email, or creates a new one.
// subscriper .
async function createCustomer(
  details: StripeCustomerDetails
): Promise<Stripe.Customer> {
  const { email, name, userId } = details;

  try {
    const existing = await stripe.customers.list({ email, limit: 1 });

    if (existing.data.length > 0) {
      return existing.data[0];
    }

    const customer = await stripe.customers.create({
      email,
      name,
      metadata: userId ? { userId } : undefined
    });

    return customer;
  } catch (error) {
    console.error("Stripe customer creation failed:", error);
    throw new Error(
      `Stripe customer creation failed: ${(error as Error).message}`
    );
  }
}

// Creates a subscription directly (customer must already have a
// payment method on file).
async function createSubscription(
  details: StripeSubscriptionDetails
): Promise<Stripe.Subscription> {
  const { customerId, priceId, trialPeriodDays } = details;

  try {
    const subscription = await stripe.subscriptions.create({
      customer: customerId,
      items: [{ price: priceId }],
      ...(trialPeriodDays ? { trial_period_days: trialPeriodDays } : {}),
      collection_method: "charge_automatically"
    });

    return subscription;
  } catch (error) {
    console.error("Stripe subscription creation failed:", error);
    throw new Error(
      `Stripe subscription creation failed: ${(error as Error).message}`
    );
  }
}

// Creates a hosted Checkout Session — the recommended Stripe flow.
async function createCheckoutSession(
  details: StripeCheckoutDetails
): Promise<Stripe.Checkout.Session> {
  const {
    priceId,
    customerId,
    customerEmail,
    successUrl,
    cancelUrl,
    trialPeriodDays,
    couponId
  } = details;
  try {
    const session = await stripe.checkout.sessions.create({
      mode: "subscription",
      line_items: [{ price: priceId, quantity: 1 }],
      customer: customerId,
      customer_email: customerId ? undefined : customerEmail,
      success_url: successUrl,
      cancel_url: cancelUrl,
      ...(couponId
        ? {
            discounts: [
              {
                coupon: couponId
              }
            ]
          }
        : {}),
      ...(trialPeriodDays
        ? { subscription_data: { trial_period_days: trialPeriodDays } }
        : {})
      // allow_promotion_codes: true
    });

    return session;
  } catch (error) {
    console.error("Stripe checkout session creation failed:", error);
    throw new Error(
      `Stripe checkout session creation failed: ${(error as Error).message}`
    );
  }
}

async function updateSubscription(data: {
  paymentProviderSubscriptionId: string;
  stripeSubscriptionItemId: string;
  paymentProviderPriceId: string;
}): Promise<Stripe.Subscription> {
  const {
    paymentProviderSubscriptionId,
    stripeSubscriptionItemId,
    paymentProviderPriceId
  } = data;

  return await stripe.subscriptions.update(paymentProviderSubscriptionId, {
    items: [
      {
        id: stripeSubscriptionItemId,
        price: paymentProviderPriceId
      }
    ]
  });
} // Create a portal session when the user clicks "Manage Billing" or "View Invoices"
async function createCustomerPortalSession(
  customerId: string,
  returnUrl: string
) {
  const portalSession =
    await stripeService.stripe.billingPortal.sessions.create({
      customer: customerId,
      return_url: returnUrl // e.g. "https://your-app.com/dashboard/billing"
    });

  return portalSession.url; // Redirect the user to this URL
}
async function retrieveSubscription(
  subscriptionId: string
): Promise<Stripe.Subscription> {
  return await stripe.subscriptions.retrieve(subscriptionId);
}
export async function updateSubscriptionCancellation(
  subscriptionId: string,
  cancelAtPeriodEnds: boolean,
  deleteImmedietly: boolean
): Promise<Stripe.Subscription> {
  if (deleteImmedietly) {
    return await stripe.subscriptions.cancel(subscriptionId);
  }
  return stripe.subscriptions.update(subscriptionId, {
    cancel_at_period_end: cancelAtPeriodEnds
  });
}
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
  stripe
};
// updateSubscriptionCancellation("sub_1UG6AQDvEnSheKucQFZ7P14k", false, true);
// console.log(generateAdminToken());
