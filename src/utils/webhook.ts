import Stripe from "stripe";

import { Plan, Subscription } from "../generated/prisma/client.js";

import { stripeService } from "../modules/subscription/External Services/Payment providers/stripe/stripeService.js";

import plansRepo from "../modules/subscription/repo/plans.repo.js";
import subscriptionRepo from "../modules/subscription/repo/subscription.repo.js";
import { ensureUsageAllocationsForSubscription } from "../modules/features/repo/usage.repo.js";
import { grantsSubscriptionAccess } from "../constants/subscription.js";

/*
 * ============================================================
 * STRIPE STATUS MAPPING
 * ============================================================
 *
 * IMPORTANT:
 *
 * Keep "trialing" separate from "active".
 *
 * Otherwise:
 *
 * Stripe trialing -> DB active
 *
 * makes it impossible to distinguish a free trial from a
 * genuinely active subscription using local subscription
 * state.
 */

export function mapStripeSubscriptionStatus(
  status: Stripe.Subscription.Status
): string {
  switch (status) {
    case "trialing":
      return "trialing";

    case "active":
      return "active";

    case "past_due":
      return "past_due";

    case "canceled":
      return "cancelled";

    case "incomplete":
      return "pending";

    case "incomplete_expired":
      return "expired";

    case "unpaid":
      return "payment_failed";

    case "paused":
      return "paused";

    default:
      return "pending";
  }
}

/*
 * ============================================================
 * EXTRACT SUBSCRIPTION ID FROM INVOICE
 * ============================================================
 *
 * Supports:
 *
 * - modern Stripe invoice.parent.subscription_details
 * - older subscription_details shapes
 * - older invoice.subscription
 */

export function extractSubscriptionId(invoice: Stripe.Invoice): string | null {
  const inv = invoice as unknown as Record<string, any>;

  /*
   * Modern Stripe API.
   */
  const parentSubscription = inv.parent?.subscription_details?.subscription;

  if (typeof parentSubscription === "string") {
    return parentSubscription;
  }

  if (parentSubscription?.id) {
    return parentSubscription.id;
  }

  /*
   * Transitional/alternative representation.
   */
  const subscriptionDetailsSubscription =
    inv.subscription_details?.subscription;

  if (typeof subscriptionDetailsSubscription === "string") {
    return subscriptionDetailsSubscription;
  }

  if (subscriptionDetailsSubscription?.id) {
    return subscriptionDetailsSubscription.id;
  }

  /*
   * Legacy Stripe API representation.
   */
  if (typeof inv.subscription === "string") {
    return inv.subscription;
  }

  if (inv.subscription?.id) {
    return inv.subscription.id;
  }

  return null;
}

/*
 * ============================================================
 * EXTRACT TENANT ID FROM INVOICE
 * ============================================================
 *
 * Do NOT rely exclusively on invoice.metadata.
 *
 * Subscription metadata may be snapshotted into the
 * subscription_details parent.
 */

export function extractTenantIdFromInvoice(
  invoice: Stripe.Invoice
): string | null {
  const inv = invoice as unknown as Record<string, any>;

  /*
   * Explicit invoice metadata.
   */
  if (invoice.metadata?.tenantId) {
    return invoice.metadata.tenantId;
  }

  /*
   * Modern Stripe parent representation.
   */
  const parentTenantId = inv.parent?.subscription_details?.metadata?.tenantId;

  if (parentTenantId) {
    return parentTenantId;
  }

  /*
   * Alternative/older subscription details.
   */
  const subscriptionDetailsTenantId =
    inv.subscription_details?.metadata?.tenantId;

  if (subscriptionDetailsTenantId) {
    return subscriptionDetailsTenantId;
  }

  return null;
}

/*
 * ============================================================
 * STRIPE CUSTOMER ID
 * ============================================================
 */

export function extractCustomerId(subscription: Stripe.Subscription): string {
  if (typeof subscription.customer === "string") {
    return subscription.customer;
  }

  return subscription.customer.id;
}

/*
 * ============================================================
 * BILLING PLAN RESOLUTION
 * ============================================================
 */

async function resolvePlanAndBillingPeriod(priceId: string): Promise<{
  plan: Plan;
  billingPeriod: string;
}> {
  const plan = (await plansRepo.getPlanByPriceId(priceId)) as Plan | null;

  if (!plan) {
    throw new Error(`Local plan not found for Stripe Price ID: ${priceId}`);
  }

  const billingOptions = (plan.billingOptions as any[]) || [];

  const matchedOption = billingOptions.find(
    (option) => option.stripePriceId === priceId
  );

  /*
   * DO NOT silently fall back to "monthly".
   *
   * If a yearly price is missing from your local
   * configuration, silently recording it as monthly is a
   * dangerous billing-data corruption bug.
   */
  if (!matchedOption?.period) {
    throw new Error(`Billing option not found for Stripe Price ID: ${priceId}`);
  }

  return {
    plan,
    billingPeriod: matchedOption.period
  };
}

/*
 * ============================================================
 * CREATE LOCAL SUBSCRIPTION FROM STRIPE OBJECT
 * ============================================================
 */

async function createSubscriptionFromStripeObject(
  subscription: Stripe.Subscription,
  targetTenantId: string
): Promise<Subscription> {
  const item = subscription.items.data[0];

  if (!item) {
    throw new Error(
      `Stripe subscription ${subscription.id} has no subscription items`
    );
  }

  const priceId = item.price.id;

  const { plan, billingPeriod } = await resolvePlanAndBillingPeriod(priceId);

  const localSubscription = await subscriptionRepo.createSubscription({
    tenantId: targetTenantId,

    plan: {
      connect: {
        id: plan.id
      }
    },

    paymentProvider: "stripe",

    paymentProviderCustomerId: extractCustomerId(subscription),

    paymentProviderSubscriptionId: subscription.id,

    paymentProviderPriceId: priceId,

    billingPeriod,

    currentPeriodStart: new Date(item.current_period_start * 1000),

    currentPeriodEnd: new Date(item.current_period_end * 1000),

    status: mapStripeSubscriptionStatus(subscription.status),

    cancelAtPeriodEnd: subscription.cancel_at_period_end,

    cancelledAt: subscription.canceled_at
      ? new Date(subscription.canceled_at * 1000)
      : null
  });

  if (grantsSubscriptionAccess(localSubscription.status)) {
    await ensureUsageAllocationsForSubscription({
      subscriptionId: localSubscription.id,
      planId: plan.id,
      periodStart: localSubscription.currentPeriodStart,
      periodEnd: localSubscription.currentPeriodEnd
    });
  }

  return localSubscription;
}

/*
 * ============================================================
 * INSERT WRAPPER
 * ============================================================
 *
 * Kept with the same exported function name so existing
 * code elsewhere doesn't break.
 */

export async function insertSubscriptionWrapper(
  subscriptionId: string,
  targetTenantId: string
): Promise<Subscription> {
  const stripeSubscription =
    await stripeService.stripe.subscriptions.retrieve(subscriptionId);

  const existing =
    await subscriptionRepo.getSubscriptionByPaymentProviderId(subscriptionId);

  /*
   * Protect against webhook race conditions.
   */
  if (existing) {
    return existing;
  }

  return await createSubscriptionFromStripeObject(
    stripeSubscription,
    targetTenantId
  );
}

/*
 * ============================================================
 * SYNCHRONIZE STRIPE SUBSCRIPTION
 * ============================================================
 *
 * UPSERT semantics.
 *
 * This function deliberately DOES NOT touch:
 *
 * scheduledPlanId
 * scheduledBillingPeriod
 *
 * because an ordinary customer.subscription.updated event
 * must not erase a future scheduled downgrade/upgrade.
 */

export async function syncSubscriptionFromStripe(
  stripeSubscription: Stripe.Subscription,
  fallbackTenantId?: string
): Promise<void> {
  let currentSubscription =
    await subscriptionRepo.getSubscriptionByPaymentProviderId(
      stripeSubscription.id
    );

  /*
   * Subscription doesn't exist locally.
   */
  if (!currentSubscription) {
    const tenantId = fallbackTenantId ?? stripeSubscription.metadata?.tenantId;

    if (!tenantId) {
      throw new Error(
        `Cannot create local Stripe subscription ` +
          `${stripeSubscription.id}: tenantId is unavailable`
      );
    }

    try {
      await createSubscriptionFromStripeObject(stripeSubscription, tenantId);
    } catch (error: any) {
      /*
       * A second concurrent webhook might have created the
       * subscription between our SELECT and INSERT.
       *
       * Check once again before failing.
       */
      currentSubscription =
        await subscriptionRepo.getSubscriptionByPaymentProviderId(
          stripeSubscription.id
        );

      if (!currentSubscription) {
        throw error;
      }
    }

    /*
     * Re-fetch after creation/race resolution.
     */
    currentSubscription =
      await subscriptionRepo.getSubscriptionByPaymentProviderId(
        stripeSubscription.id
      );
  }

  if (!currentSubscription) {
    throw new Error(
      `Failed to synchronize local subscription ${stripeSubscription.id}`
    );
  }

  const item = stripeSubscription.items.data[0];

  if (!item) {
    throw new Error(
      `No subscription item found in Stripe subscription: ` +
        `${stripeSubscription.id}`
    );
  }

  const priceId = item.price.id;

  const { plan, billingPeriod } = await resolvePlanAndBillingPeriod(priceId);

  await subscriptionRepo.updateSubscription(currentSubscription.id, {
    planId: plan.id,

    paymentProviderCustomerId: extractCustomerId(stripeSubscription),

    paymentProviderPriceId: priceId,

    billingPeriod,

    status: mapStripeSubscriptionStatus(stripeSubscription.status),

    currentPeriodStart: new Date(item.current_period_start * 1000),

    currentPeriodEnd: new Date(item.current_period_end * 1000),

    cancelAtPeriodEnd: stripeSubscription.cancel_at_period_end,

    cancelledAt: stripeSubscription.canceled_at
      ? new Date(stripeSubscription.canceled_at * 1000)
      : null

    /*
     * DO NOT DO:
     *
     * scheduledPlanId: null,
     * scheduledBillingPeriod: null
     *
     * Generic subscription updates happen for many reasons.
     */
  });

  const mappedStatus = mapStripeSubscriptionStatus(stripeSubscription.status);
  if (grantsSubscriptionAccess(mappedStatus)) {
    await ensureUsageAllocationsForSubscription({
      subscriptionId: currentSubscription.id,
      planId: plan.id,
      periodStart: new Date(item.current_period_start * 1000),
      periodEnd: new Date(item.current_period_end * 1000)
    });
  }
}

/*
 * ============================================================
 * ENSURE SUBSCRIPTION EXISTS FOR AN INVOICE
 * ============================================================
 *
 * Makes invoice handlers independent of webhook ordering.
 */

export async function ensureLocalSubscriptionForInvoice(
  invoice: Stripe.Invoice
): Promise<Subscription> {
  const stripeSubscriptionId = extractSubscriptionId(invoice);

  if (!stripeSubscriptionId) {
    throw new Error(
      `Invoice ${invoice.id} is not connected to a Stripe subscription`
    );
  }

  const existing =
    await subscriptionRepo.getSubscriptionByPaymentProviderId(
      stripeSubscriptionId
    );

  if (existing) {
    return existing;
  }

  /*
   * Retrieve the authoritative subscription.
   */
  const stripeSubscription =
    await stripeService.stripe.subscriptions.retrieve(stripeSubscriptionId);

  /*
   * First try invoice metadata.
   *
   * Then try Stripe Subscription metadata.
   */
  const tenantId =
    extractTenantIdFromInvoice(invoice) ??
    stripeSubscription.metadata?.tenantId ??
    null;

  if (!tenantId) {
    throw new Error(
      `Cannot create subscription ${stripeSubscriptionId} ` +
        `from invoice ${invoice.id}: tenantId is unavailable`
    );
  }

  /*
   * Another webhook could have inserted it during the API
   * request, so check again.
   */
  const existingAfterRetrieve =
    await subscriptionRepo.getSubscriptionByPaymentProviderId(
      stripeSubscriptionId
    );

  if (existingAfterRetrieve) {
    return existingAfterRetrieve;
  }

  try {
    return await createSubscriptionFromStripeObject(
      stripeSubscription,
      tenantId
    );
  } catch (error: any) {
    /*
     * Final race-condition protection.
     */
    const concurrentSubscription =
      await subscriptionRepo.getSubscriptionByPaymentProviderId(
        stripeSubscriptionId
      );

    if (concurrentSubscription) {
      return concurrentSubscription;
    }

    throw error;
  }
}

/*
 * ============================================================
 * EXTRACT PAYMENT INTENT
 * ============================================================
 *
 * Supports both:
 *
 * OLD:
 * invoice.payment_intent
 *
 * NEW:
 * invoice.payments.data[n].payment.payment_intent
 */

export function extractPaymentIntentId(invoice: Stripe.Invoice): string | null {
  const inv = invoice as unknown as Record<string, any>;

  /*
   * Older Stripe API.
   */
  if (typeof inv.payment_intent === "string") {
    return inv.payment_intent;
  }

  if (inv.payment_intent?.id) {
    return inv.payment_intent.id;
  }

  /*
   * Newer InvoicePayment representation.
   */
  const invoicePayments = inv.payments?.data;

  if (Array.isArray(invoicePayments)) {
    for (const invoicePayment of invoicePayments) {
      const payment = invoicePayment?.payment;

      if (payment?.type !== "payment_intent") {
        continue;
      }

      const paymentIntent = payment.payment_intent;

      if (typeof paymentIntent === "string") {
        return paymentIntent;
      }

      if (paymentIntent?.id) {
        return paymentIntent.id;
      }
    }
  }

  return null;
}

/*
 * ============================================================
 * RESOLVE PAYMENT INTENT
 * ============================================================
 *
 * Invoice.payments isn't always included in webhook payloads,
 * so retrieve the invoice with payments expanded when needed.
 */

export async function resolvePaymentIntentId(
  invoice: Stripe.Invoice
): Promise<string | null> {
  /*
   * First attempt: webhook payload itself.
   */
  const directPaymentIntentId = extractPaymentIntentId(invoice);

  if (directPaymentIntentId) {
    return directPaymentIntentId;
  }

  try {
    const expandedInvoice = await stripeService.stripe.invoices.retrieve(
      invoice.id,
      {
        expand: ["payments"]
      }
    );

    return extractPaymentIntentId(expandedInvoice as Stripe.Invoice);
  } catch (error) {
    console.warn(
      `[Stripe] Could not resolve PaymentIntent ` +
        `for invoice ${invoice.id}:`,
      error
    );

    return null;
  }
}
