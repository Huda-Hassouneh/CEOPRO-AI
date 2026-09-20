import Stripe from "stripe";

import type {
  StripePriceDetails,
  StripeService,
  StripeCustomerDetails,
  StripeSubscriptionDetails,
  StripeCheckoutDetails
} from "../../../../../types/Payment Providers/stripe.js";

/*
 * ============================================================================
 * CONFIGURATION
 * ============================================================================
 */

const STRIPE_SECRET_KEY = process.env.STRIPE_SECRET_KEY;

if (!STRIPE_SECRET_KEY) {
  throw new Error("STRIPE_SECRET_KEY is not configured");
}

/*
 * A small number of automatic network retries is useful for
 * transient Stripe/network failures.
 */
export const stripe = new Stripe(STRIPE_SECRET_KEY, {
  maxNetworkRetries: 2
});

/*
 * ============================================================================
 * INTERNAL HELPERS
 * ============================================================================
 */

/*
 * Stripe uses expandable fields extensively.
 *
 * A field can be:
 *
 * "sub_123"
 *
 * OR
 *
 * {
 *   id: "sub_123",
 *   ...
 * }
 *
 * This helper safely extracts the ID.
 */
function getExpandableId(
  value:
    | string
    | {
        id: string;
      }
    | null
    | undefined
): string | null {
  if (!value) {
    return null;
  }

  if (typeof value === "string") {
    return value;
  }

  return value.id ?? null;
}

/*
 * Resolve a Price ID from an expandable Price.
 */
function getPriceId(
  price:
    | string
    | {
        id: string;
      }
): string {
  return typeof price === "string" ? price : price.id;
}

/*
 * ============================================================================
 * CATALOG & PLANS
 * ============================================================================
 */

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

      metadata: {
        type: "SERVICE",
        category: "SOFTWARE"
      }
    });
  } catch (error) {
    console.error("Stripe create catalog failed:", error);

    throw new Error(
      `Stripe catalog creation failed: ${(error as Error).message}`
    );
  }
}

/*
 * ============================================================================
 * CREATE PRICE / PLAN
 * ============================================================================
 *
 * IMPORTANT:
 *
 * Trial configuration DOES NOT belong on the Price creation
 * request.
 *
 * Trial duration is applied when the Subscription or Checkout
 * Session is created.
 */

export async function createPlan(
  productId: string,
  planDetails: StripePriceDetails
): Promise<Stripe.Price> {
  if (!productId) {
    throw new Error("Stripe product ID is required");
  }

  const { name, description, unitAmount, currency, interval, intervalCount } =
    planDetails;

  if (unitAmount < 0) {
    throw new Error("Stripe price amount cannot be negative");
  }

  try {
    return await stripe.prices.create({
      product: productId,

      nickname: name,

      currency: currency.toLowerCase(),

      /*
       * Stripe expects amounts in the currency's
       * minor unit.
       *
       * Your current project uses currencies such as
       * JOD/USD that Stripe treats as decimal currencies.
       */
      unit_amount: Math.round(unitAmount * 100),

      recurring: {
        interval,

        interval_count: intervalCount ?? 1
      },

      metadata: description
        ? {
            description
          }
        : undefined
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

/*
 * ============================================================================
 * CUSTOMERS
 * ============================================================================
 */

type ExtendedStripeCustomerDetails = StripeCustomerDetails & {
  /*
   * Your internal tenant ID.
   *
   * Keep this separate from userId because:
   *
   * user != tenant
   *
   * in a multi-tenant system.
   */
  tenantId?: string;
};

/*
 * ============================================================================
 * CREATE / REUSE CUSTOMER
 * ============================================================================
 *
 * IMPORTANT FIX:
 *
 * Do NOT blindly reuse the first Stripe Customer that has the
 * same email address.
 *
 * Two tenants can theoretically use the same email address.
 *
 * When tenantId is available we only reuse a Stripe Customer
 * associated with that tenant.
 */

export async function createCustomer(
  details: ExtendedStripeCustomerDetails
): Promise<Stripe.Customer> {
  const { email, name, userId, tenantId } = details;

  if (!email) {
    throw new Error("Customer email is required");
  }

  try {
    /*
     * Stripe supports filtering Customer list by email.
     *
     * We retrieve more than one because email alone should
     * not determine tenant ownership.
     */
    const existingCustomers = await stripe.customers.list({
      email,
      limit: 100
    });

    let existingCustomer: Stripe.Customer | undefined;

    /*
     * Prefer exact tenant match.
     */
    if (tenantId) {
      existingCustomer = existingCustomers.data.find(
        (customer) => customer.metadata?.tenantId === tenantId
      );
    }

    /*
     * Backwards compatibility:
     *
     * An older Customer might have userId but not tenantId.
     */
    if (!existingCustomer && userId) {
      existingCustomer = existingCustomers.data.find(
        (customer) => customer.metadata?.userId === userId
      );
    }

    /*
     * If neither tenantId nor userId was supplied,
     * preserve the old email-based behavior.
     */
    if (!existingCustomer && !tenantId && !userId) {
      existingCustomer = existingCustomers.data[0];
    }

    /*
     * Existing correct Customer found.
     *
     * Synchronize metadata so older Stripe customers gain
     * the newer tenantId metadata.
     */
    if (existingCustomer) {
      const updatedMetadata = {
        ...existingCustomer.metadata,

        ...(userId
          ? {
              userId
            }
          : {}),

        ...(tenantId
          ? {
              tenantId
            }
          : {})
      };

      return await stripe.customers.update(existingCustomer.id, {
        ...(name
          ? {
              name
            }
          : {}),

        metadata: updatedMetadata
      });
    }

    /*
     * No customer for this tenant/user.
     *
     * Create a new Stripe Customer.
     */
    return await stripe.customers.create({
      email,

      ...(name
        ? {
            name
          }
        : {}),

      metadata: {
        ...(userId
          ? {
              userId
            }
          : {}),

        ...(tenantId
          ? {
              tenantId
            }
          : {})
      }
    });
  } catch (error) {
    console.error("Stripe customer creation failed:", error);

    throw new Error(
      `Stripe customer creation failed: ${(error as Error).message}`
    );
  }
}

/*
 * ============================================================================
 * DELETE CUSTOMER
 * ============================================================================
 */

export async function deleteCustomerByCustomerId(
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

/*
 * ============================================================================
 * CUSTOMER PORTAL
 * ============================================================================
 */

export async function createCustomerPortalSession(
  customerId: string,
  returnUrl: string
): Promise<string> {
  if (!customerId) {
    throw new Error("Stripe Customer ID is required");
  }

  if (!returnUrl) {
    throw new Error("Customer portal return URL is required");
  }

  try {
    const portalSession = await stripe.billingPortal.sessions.create({
      customer: customerId,

      return_url: returnUrl
    });

    return portalSession.url;
  } catch (error) {
    console.error("Stripe customer portal creation failed:", error);

    throw new Error(
      `Stripe customer portal creation failed: ${(error as Error).message}`
    );
  }
}

/*
 * ============================================================================
 * PROMO CODES / COUPONS
 * ============================================================================
 */

export async function createPromoCode(
  type: string,
  amount: number,
  discountAppliedFor: string = "once",
  currency: string = "usd"
): Promise<Stripe.Coupon> {
  if (amount <= 0) {
    throw new Error("Discount amount must be greater than 0");
  }

  if (type === "percentage" && amount > 100) {
    throw new Error("Percentage discount cannot exceed 100%");
  }

  /*
   * Stripe's repeating coupon duration is deprecated.
   *
   * Keep this service limited to the clean supported
   * behavior used by this application.
   */
  if (discountAppliedFor !== "once" && discountAppliedFor !== "forever") {
    throw new Error("discountAppliedFor must be 'once' or 'forever'");
  }

  const duration = discountAppliedFor as "once" | "forever";

  try {
    /*
     * Percentage coupons don't require currency.
     *
     * Fixed amount coupons DO require currency.
     */
    if (type === "percentage") {
      return await stripe.coupons.create({
        percent_off: amount,

        duration
      });
    }

    /*
     * IMPORTANT:
     *
     * For fixed discounts, amount must already be in the
     * Stripe minor currency unit.
     *
     * Example:
     *
     * 5.00 USD => amount = 500
     */
    return await stripe.coupons.create({
      amount_off: amount,

      currency: currency.toLowerCase(),

      duration
    });
  } catch (error) {
    console.error("Stripe coupon creation failed:", error);

    throw new Error(
      `Stripe coupon creation failed: ${(error as Error).message}`
    );
  }
}

/*
 * ============================================================================
 * CHECKOUT
 * ============================================================================
 */

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

  if (!priceId) {
    throw new Error("Stripe Price ID is required");
  }

  if (!tenantId) {
    throw new Error(
      "tenantId is required when creating a subscription Checkout Session"
    );
  }

  if (!customerId && !customerEmail) {
    throw new Error("Either customerId or customerEmail is required");
  }

  if (!successUrl) {
    throw new Error("Checkout success URL is required");
  }

  if (!cancelUrl) {
    throw new Error("Checkout cancel URL is required");
  }

  try {
    return await stripe.checkout.sessions.create({
      mode: "subscription",

      line_items: [
        {
          price: priceId,

          quantity: 1
        }
      ],

      /*
       * Existing Stripe Customer.
       */
      ...(customerId
        ? {
            customer: customerId
          }
        : {
            customer_email: customerEmail
          }),

      success_url: successUrl,

      cancel_url: cancelUrl,

      /*
       * Internal tenant reconciliation.
       */
      client_reference_id: tenantId,

      /*
       * Metadata on the Checkout Session itself.
       */
      metadata: {
        tenantId
      },

      /*
       * Explicitly collect a payment method.
       *
       * This is important for your business flow:
       *
       * free trial
       *      ↓
       * payment method already saved
       *      ↓
       * Stripe automatically charges after trial
       */
      payment_method_collection: "always",

      /*
       * Metadata and trial settings on the resulting
       * Stripe Subscription.
       */
      subscription_data: {
        metadata: {
          tenantId
        },

        /*
         * Only add trial configuration when there is
         * actually a positive trial period.
         */
        ...(trialPeriodDays && trialPeriodDays > 0
          ? {
              trial_period_days: trialPeriodDays,

              /*
               * This is only a safety fallback.
               *
               * Since payment_method_collection="always",
               * normally a payment method exists.
               *
               * If somehow it doesn't, pausing is safer than
               * creating unpaid invoices indefinitely.
               */
              trial_settings: {
                end_behavior: {
                  missing_payment_method: "pause"
                }
              }
            }
          : {})
      },

      /*
       * Optional coupon.
       */
      ...(couponId
        ? {
            discounts: [
              {
                coupon: couponId
              }
            ]
          }
        : {})
    });
  } catch (error) {
    console.error("Stripe checkout session creation failed:", error);

    throw new Error(
      `Stripe checkout session creation failed: ${(error as Error).message}`
    );
  }
}

/*
 * ============================================================================
 * DIRECT SUBSCRIPTION CREATION
 * ============================================================================
 *
 * This isn't used by your Checkout flow, but we keep it
 * consistent with the same metadata/trial architecture.
 */

type ExtendedStripeSubscriptionDetails = StripeSubscriptionDetails & {
  tenantId?: string;
};

export async function createSubscription(
  details: ExtendedStripeSubscriptionDetails
): Promise<Stripe.Subscription> {
  const { customerId, priceId, trialPeriodDays, tenantId } = details;

  if (!customerId) {
    throw new Error("Stripe Customer ID is required");
  }

  if (!priceId) {
    throw new Error("Stripe Price ID is required");
  }

  try {
    return await stripe.subscriptions.create({
      customer: customerId,

      items: [
        {
          price: priceId
        }
      ],

      collection_method: "charge_automatically",

      /*
       * Better initial-payment/SCA behavior than pretending
       * the subscription is immediately active.
       */
      payment_behavior: "default_incomplete",

      ...(tenantId
        ? {
            metadata: {
              tenantId
            }
          }
        : {}),

      ...(trialPeriodDays && trialPeriodDays > 0
        ? {
            trial_period_days: trialPeriodDays,

            trial_settings: {
              end_behavior: {
                missing_payment_method: "pause"
              }
            }
          }
        : {})
    });
  } catch (error) {
    console.error("Stripe subscription creation failed:", error);

    throw new Error(
      `Stripe subscription creation failed: ${(error as Error).message}`
    );
  }
}

/*
 * ============================================================================
 * RETRIEVE SUBSCRIPTION
 * ============================================================================
 */

export async function retrieveSubscription(
  subscriptionId: string
): Promise<Stripe.Subscription> {
  if (!subscriptionId) {
    throw new Error("Stripe Subscription ID is required");
  }

  return await stripe.subscriptions.retrieve(subscriptionId);
}

/*
 * ============================================================================
 * UPDATE SUBSCRIPTION
 * ============================================================================
 *
 * BUSINESS RULE:
 *
 * UPGRADE
 * ───────
 *
 * Apply immediately.
 *
 * Generate prorations.
 *
 * Immediately invoice + attempt payment.
 *
 *
 * DOWNGRADE
 * ─────────
 *
 * Keep current plan until current billing period ends.
 *
 * Schedule the cheaper/new plan for the next period.
 */

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

  if (!paymentProviderSubscriptionId) {
    throw new Error("Stripe Subscription ID is required");
  }

  if (!stripeSubscriptionItemId) {
    throw new Error("Stripe Subscription Item ID is required");
  }

  if (!paymentProviderPriceId) {
    throw new Error("Stripe Price ID is required");
  }

  /*
   * Retrieve authoritative current state.
   */
  let subscription = await stripe.subscriptions.retrieve(
    paymentProviderSubscriptionId
  );

  /*
   * ========================================================
   * UPGRADE
   * ========================================================
   */

  if (action === "upgrade") {
    /*
     * If a future downgrade is already scheduled, release it
     * before performing the immediate upgrade.
     */
    const scheduleId = getExpandableId(subscription.schedule);

    if (scheduleId) {
      console.log(
        `[Stripe] Releasing pending schedule ${scheduleId} before upgrade.`
      );

      await stripe.subscriptionSchedules.release(scheduleId, {
        /*
         * Don't accidentally remove a cancellation date
         * that might exist on the underlying subscription.
         */
        preserve_cancel_date: true
      });

      /*
       * Refresh after release.
       */
      subscription = await stripe.subscriptions.retrieve(
        paymentProviderSubscriptionId
      );
    }

    /*
     * IMPORTANT:
     *
     * always_invoice:
     *
     * - creates prorations
     * - creates invoice immediately
     * - attempts payment immediately
     *
     * pending_if_incomplete:
     *
     * If payment requires action/fails, Stripe keeps the
     * update pending rather than pretending the paid upgrade
     * has already completed.
     */
    return await stripe.subscriptions.update(paymentProviderSubscriptionId, {
      items: [
        {
          id: stripeSubscriptionItemId,

          price: paymentProviderPriceId,

          quantity: 1
        }
      ],

      proration_behavior: "always_invoice",

      payment_behavior: "pending_if_incomplete"
    });
  }

  /*
   * ========================================================
   * DOWNGRADE
   * ========================================================
   *
   * Downgrade should NOT immediately change the current plan.
   *
   * Instead:
   *
   * Current plan
   *       ↓
   * remains active until current period end
   *       ↓
   * next phase uses downgraded Price
   */

  let scheduleId = getExpandableId(subscription.schedule);

  /*
   * Create a Subscription Schedule from the existing
   * subscription if one doesn't already exist.
   */
  if (!scheduleId) {
    const schedule = await stripe.subscriptionSchedules.create({
      from_subscription: paymentProviderSubscriptionId
    });

    scheduleId = schedule.id;
  }

  const schedule = await stripe.subscriptionSchedules.retrieve(scheduleId);

  /*
   * Find the ACTUAL current phase.
   *
   * Don't blindly use phases[0], because an existing schedule
   * may contain past/current/future phases.
   */
  let currentPhase = schedule.current_phase
    ? schedule.phases.find(
        (phase) =>
          phase.start_date === schedule.current_phase?.start_date &&
          phase.end_date === schedule.current_phase?.end_date
      )
    : undefined;

  /*
   * Fresh schedules created from_subscription normally have
   * one active phase, but keep a safe fallback.
   */
  if (!currentPhase) {
    currentPhase = schedule.phases.find(
      (phase) => phase.end_date > Math.floor(Date.now() / 1000)
    );
  }

  if (!currentPhase) {
    throw new Error(
      `Could not resolve the current phase for Stripe schedule ${scheduleId}`
    );
  }

  /*
   * Preserve the current phase items exactly until the end
   * of the billing period.
   */
  const currentPhaseItems = currentPhase.items.map((item) => ({
    price: getPriceId(item.price),

    quantity: item.quantity ?? 1
  }));

  /*
   * Replace future schedule with:
   *
   * Phase 1 = existing current plan until current phase end
   * Phase 2 = downgraded plan afterward
   */
  await stripe.subscriptionSchedules.update(scheduleId, {
    /*
     * Once the downgrade has applied, release schedule
     * management and let the Subscription continue
     * normally.
     */
    end_behavior: "release",

    phases: [
      {
        start_date: currentPhase.start_date,

        end_date: currentPhase.end_date,

        items: currentPhaseItems
      },

      {
        /*
         * Stripe automatically starts this phase when the
         * previous phase ends.
         */
        items: [
          {
            price: paymentProviderPriceId,

            quantity: 1
          }
        ]
      }
    ]
  });

  /*
   * The current Stripe Subscription still represents the
   * current plan.
   *
   * Your local scheduledPlanId /
   * scheduledBillingPeriod should represent the future plan.
   */
  return await stripe.subscriptions.retrieve(paymentProviderSubscriptionId);
}

/*
 * ============================================================================
 * SUBSCRIPTION CANCELLATION
 * ============================================================================
 */

export async function updateSubscriptionCancellation(
  subscriptionId: string,
  cancelAtPeriodEnds: boolean,
  deleteImmediately: boolean
): Promise<Stripe.Subscription> {
  if (!subscriptionId) {
    throw new Error("Stripe Subscription ID is required");
  }

  let subscription = await stripe.subscriptions.retrieve(subscriptionId);

  /*
   * If a future downgrade/plan change exists and the user
   * changes cancellation state, release the schedule first.
   *
   * The cancellation request now becomes the authoritative
   * future action.
   */
  const scheduleId = getExpandableId(subscription.schedule);

  if (scheduleId) {
    console.log(
      `[Stripe] Releasing schedule ${scheduleId} before cancellation update.`
    );

    await stripe.subscriptionSchedules.release(scheduleId, {
      /*
       * Preserve existing cancellation information during
       * schedule release.
       */
      preserve_cancel_date: true
    });

    subscription = await stripe.subscriptions.retrieve(subscriptionId);
  }

  /*
   * Immediate cancellation.
   */
  if (deleteImmediately) {
    return await stripe.subscriptions.cancel(subscriptionId);
  }

  /*
   * Cancel / undo cancellation at end of billing period.
   */
  return await stripe.subscriptions.update(subscriptionId, {
    cancel_at_period_end: cancelAtPeriodEnds
  });
}

/*
 * ============================================================================
 * SERVICE EXPORT
 * ============================================================================
 */

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
