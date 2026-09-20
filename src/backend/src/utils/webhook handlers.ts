import Stripe from "stripe";

import { stripeService } from "../modules/subscription/External Services/Payment providers/stripe/stripeService.js";

import subscriptionRepo from "../modules/subscription/repo/subscription.repo.js";
import webhookRepo from "../modules/subscription/repo/webhook.repo.js";

import {
  ensureLocalSubscriptionForInvoice,
  extractSubscriptionId,
  resolvePaymentIntentId,
  syncSubscriptionFromStripe
} from "./webhook.js";

import { consumePromocode } from "../modules/subscription/repo/promocodes.repo.js";

/*
 * ============================================================
 * CHECKOUT COMPLETED
 * ============================================================
 */

export async function handleCheckoutSessionCompleted(
  session: Stripe.Checkout.Session
) {
  if (!session.subscription) {
    console.warn(
      `[Stripe] Checkout session ${session.id} completed without a subscription ID`
    );

    return;
  }

  const stripeSubscriptionId =
    typeof session.subscription === "string"
      ? session.subscription
      : session.subscription.id;

  /*
   * Checkout Session metadata is useful during initial
   * creation, especially if subscription_data.metadata
   * wasn't also supplied.
   */
  const tenantId = session.metadata?.tenantId ?? undefined;

  const stripeSubscription =
    await stripeService.stripe.subscriptions.retrieve(stripeSubscriptionId);

  /*
   * This acts as an UPSERT.
   *
   * Therefore it is safe if:
   *
   * customer.subscription.created
   *
   * arrived before checkout.session.completed.
   */
  await syncSubscriptionFromStripe(stripeSubscription, tenantId);

  console.info(
    `[Stripe] Checkout session synchronized: ` +
      `${session.id} -> ${stripeSubscriptionId}`
  );
}

/*
 * ============================================================
 * SUBSCRIPTION CREATED
 * ============================================================
 */

export async function handleSubscriptionCreated(
  subscription: Stripe.Subscription
) {
  const existingSubscription =
    await subscriptionRepo.getSubscriptionByPaymentProviderId(subscription.id);

  /*
   * If customer.subscription.created arrives before
   * checkout.session.completed, and tenantId exists only
   * on Checkout Session metadata, we don't have enough
   * information yet to create the local subscription.
   *
   * Checkout completion will create it shortly afterward.
   */
  if (!existingSubscription && !subscription.metadata?.tenantId) {
    console.warn(
      `[Stripe] Subscription ${subscription.id} created, ` +
        `but tenantId is unavailable. Waiting for another event ` +
        `such as checkout.session.completed.`
    );

    return;
  }

  await syncSubscriptionFromStripe(
    subscription,
    subscription.metadata?.tenantId
  );
}

/*
 * ============================================================
 * SUBSCRIPTION UPDATED / PAUSED / RESUMED
 * ============================================================
 */

export async function handleSubscriptionUpdated(
  subscription: Stripe.Subscription
) {
  await syncSubscriptionFromStripe(
    subscription,
    subscription.metadata?.tenantId
  );
}

/*
 * ============================================================
 * SUBSCRIPTION DELETED
 * ============================================================
 */

export async function handleSubscriptionDeleted(
  stripeSubscription: Stripe.Subscription
) {
  /*
   * Synchronize first so cancellation status, periods,
   * plan information, etc. reflect Stripe.
   */
  await syncSubscriptionFromStripe(
    stripeSubscription,
    stripeSubscription.metadata?.tenantId
  );

  const currentSubscription =
    await subscriptionRepo.getSubscriptionByPaymentProviderId(
      stripeSubscription.id
    );

  if (!currentSubscription) {
    console.warn(
      `[Stripe] Deleted subscription ${stripeSubscription.id} ` +
        `could not be found locally after synchronization`
    );

    return;
  }

  /*
   * Subscription is terminal, therefore pending local
   * schedule state is no longer useful.
   */
  await subscriptionRepo.updateSubscription(currentSubscription.id, {
    cancelAtPeriodEnd: false,

    scheduledPlanId: null,
    scheduledBillingPeriod: null
  });
}

/*
 * ============================================================
 * TRIAL WILL END
 * ============================================================
 */

export async function handleSubscriptionTrialWillEnd(
  subscription: Stripe.Subscription
) {
  await syncSubscriptionFromStripe(
    subscription,
    subscription.metadata?.tenantId
  );

  console.info(`[Stripe] Trial will end for subscription ${subscription.id}`);

  /*
   * Add your notification logic here if needed:
   *
   * - email tenant
   * - notification in dashboard
   * - verify default payment method
   *
   * Do NOT mark it as payment_failed here.
   */
}

/*
 * ============================================================
 * INVOICE PAID
 * ============================================================
 *
 * Invoice successfully reached the "paid" state.
 *
 * IMPORTANT:
 *
 * This does NOT necessarily mean Stripe collected money.
 *
 * invoice.paid can also occur when the invoice was marked
 * paid out-of-band.
 *
 * Therefore we:
 *
 * 1. ensure subscription exists
 * 2. sync subscription
 * 3. process promo-code redemption
 *
 * Monetary payment records are created by
 * invoice.payment_succeeded instead.
 */

export async function handleInvoicePaid(invoice: Stripe.Invoice) {
  const stripeSubscriptionId = extractSubscriptionId(invoice);

  if (!stripeSubscriptionId) {
    console.warn(`[Stripe] Invoice ${invoice.id} paid without a subscription`);

    return;
  }

  await ensureLocalSubscriptionForInvoice(invoice);

  /*
   * Always retrieve the authoritative current subscription.
   *
   * Webhook ordering isn't guaranteed, so don't assume a
   * customer.subscription.updated event already ran.
   */
  const stripeSubscription =
    await stripeService.stripe.subscriptions.retrieve(stripeSubscriptionId);

  await syncSubscriptionFromStripe(stripeSubscription);

  console.info(
    `[Stripe] Invoice paid: ${invoice.id}` +
      ` | billing_reason=${invoice.billing_reason}` +
      ` | amount_paid=${invoice.amount_paid}` +
      ` | currency=${invoice.currency}`
  );

  /*
   * ========================================================
   * PROMO CODE CONSUMPTION
   * ========================================================
   *
   * Keep this on invoice settlement instead of requiring
   * amount_paid > 0.
   *
   * Example:
   * a legitimate 100%-off coupon results in amount_paid=0,
   * but it should still count as redeemed.
   */
  if (
    invoice.billing_reason === "subscription_create" &&
    invoice.discounts &&
    invoice.discounts.length > 0
  ) {
    const expandedInvoice = await stripeService.stripe.invoices.retrieve(
      invoice.id,
      {
        expand: ["discounts"]
      }
    );

    const discount = expandedInvoice.discounts?.[0] as any;

    if (!discount) {
      return;
    }

    let stripeCouponId: string | undefined;

    /*
     * Support newer Stripe Discount representation.
     */
    if (discount.source?.coupon) {
      stripeCouponId =
        typeof discount.source.coupon === "string"
          ? discount.source.coupon
          : discount.source.coupon.id;
    }

    /*
     * Support older Stripe API representations.
     */
    if (!stripeCouponId && discount.coupon) {
      stripeCouponId =
        typeof discount.coupon === "string"
          ? discount.coupon
          : discount.coupon.id;
    }

    const expandedStripeSubscriptionId = extractSubscriptionId(
      expandedInvoice as Stripe.Invoice
    );

    if (stripeCouponId && expandedStripeSubscriptionId) {
      await consumePromocode(expandedStripeSubscriptionId, stripeCouponId);
    }
  }
}

/*
 * ============================================================
 * PAYMENT SUCCEEDED
 * ============================================================
 *
 * This is the handler that represents an actual successful
 * Stripe invoice payment attempt.
 */

export async function handleInvoicePaymentSucceeded(invoice: Stripe.Invoice) {
  const stripeSubscriptionId = extractSubscriptionId(invoice);

  if (!stripeSubscriptionId) {
    console.warn(
      `[Stripe] invoice.payment_succeeded ${invoice.id} ` +
        `has no subscription`
    );

    return;
  }

  const subscription = await ensureLocalSubscriptionForInvoice(invoice);

  /*
   * Synchronize subscription independently of webhook order.
   */
  const stripeSubscription =
    await stripeService.stripe.subscriptions.retrieve(stripeSubscriptionId);

  await syncSubscriptionFromStripe(stripeSubscription);

  /*
   * ========================================================
   * ZERO-DOLLAR INVOICES
   * ========================================================
   *
   * An invoice can successfully settle with amount_paid = 0.
   *
   * Examples:
   * - free trial
   * - 100% discount
   * - credits
   *
   * That is NOT a monetary transaction.
   */
  if (invoice.amount_paid <= 0) {
    console.info(
      `[Stripe] Successful zero-value invoice ignored as payment: ` +
        `${invoice.id}` +
        ` | billing_reason=${invoice.billing_reason}`
    );

    return;
  }

  /*
   * ========================================================
   * CLASSIFY PAYMENT
   * ========================================================
   */

  const paymentType =
    invoice.billing_reason === "subscription_cycle"
      ? "recurring"
      : invoice.billing_reason === "subscription_create"
        ? "initial"
        : invoice.billing_reason === "subscription_update"
          ? "subscription_change"
          : "other";

  /*
   * THIS is the actual successful transaction record.
   *
   * createInvoicePayment should itself be idempotent.
   */
  await webhookRepo.createInvoicePayment(invoice, subscription.id, "succeeded");

  console.info(
    `[Stripe][Payment] SUCCESS` +
      ` | invoice=${invoice.id}` +
      ` | subscription=${stripeSubscriptionId}` +
      ` | type=${paymentType}` +
      ` | amount=${invoice.amount_paid}` +
      ` | currency=${invoice.currency}`
  );

  /*
   * ========================================================
   * REAL RECURRING PAYMENT
   * ========================================================
   */

  if (
    invoice.billing_reason === "subscription_cycle" &&
    invoice.amount_paid > 0
  ) {
    console.info(
      `[Stripe][Recurring Payment] SUCCESS` +
        ` | invoice=${invoice.id}` +
        ` | subscription=${stripeSubscriptionId}` +
        ` | amount=${invoice.amount_paid}` +
        ` | currency=${invoice.currency}`
    );

    /*
     * This is where you can safely perform recurring
     * payment-specific business logic:
     *
     * - replenish credits
     * - create usage allocation
     * - send renewal receipt
     * - record recurring revenue event
     *
     * Make those operations idempotent by invoice.id.
     */
  }
}

/*
 * ============================================================
 * PAYMENT FAILED
 * ============================================================
 */

export async function handleInvoicePaymentFailed(invoice: Stripe.Invoice) {
  const stripeSubscriptionId = extractSubscriptionId(invoice);

  if (!stripeSubscriptionId) {
    console.warn(
      `[Stripe] Invoice ${invoice.id} payment failed ` + `without subscription`
    );

    return;
  }

  const subscription = await ensureLocalSubscriptionForInvoice(invoice);

  /*
   * DO NOT blindly set local status = "past_due".
   *
   * Initial payment failure may produce "incomplete".
   * Renewal failure commonly produces "past_due".
   *
   * Stripe is the source of truth.
   */
  const stripeSubscription =
    await stripeService.stripe.subscriptions.retrieve(stripeSubscriptionId);

  await syncSubscriptionFromStripe(stripeSubscription);

  /*
   * ========================================================
   * FAILURE REASON
   * ========================================================
   */

  let failureReason: string | null = null;

  const paymentIntentId = await resolvePaymentIntentId(invoice);

  if (paymentIntentId) {
    try {
      const paymentIntent =
        await stripeService.stripe.paymentIntents.retrieve(paymentIntentId);

      failureReason =
        paymentIntent.last_payment_error?.message ??
        paymentIntent.last_payment_error?.decline_code ??
        paymentIntent.last_payment_error?.code ??
        null;
    } catch (error) {
      console.warn(
        `[Stripe] Could not retrieve PaymentIntent ` +
          `${paymentIntentId} for invoice ${invoice.id}`,
        error
      );
    }
  }

  if (!failureReason) {
    failureReason = "Payment collection failed";
  }

  await webhookRepo.createInvoicePayment(
    invoice,
    subscription.id,
    "failed",
    failureReason
  );

  console.warn(
    `[Stripe][Payment] FAILED` +
      ` | invoice=${invoice.id}` +
      ` | subscription=${stripeSubscriptionId}` +
      ` | reason=${failureReason}`
  );
}

/*
 * ============================================================
 * PAYMENT ACTION REQUIRED
 * ============================================================
 *
 * Common example:
 * 3D Secure / SCA authentication.
 */

export async function handleInvoicePaymentActionRequired(
  invoice: Stripe.Invoice
) {
  const stripeSubscriptionId = extractSubscriptionId(invoice);

  if (!stripeSubscriptionId) {
    console.warn(
      `[Stripe] Invoice ${invoice.id} requires payment action ` +
        `but is not connected to a subscription`
    );

    return;
  }

  await ensureLocalSubscriptionForInvoice(invoice);

  const stripeSubscription =
    await stripeService.stripe.subscriptions.retrieve(stripeSubscriptionId);

  await syncSubscriptionFromStripe(stripeSubscription);

  const paymentIntentId = await resolvePaymentIntentId(invoice);

  console.warn(
    `[Stripe][Payment Action Required]` +
      ` | invoice=${invoice.id}` +
      ` | subscription=${stripeSubscriptionId}` +
      ` | paymentIntent=${paymentIntentId ?? "unknown"}`
  );

  /*
   * Add customer notification here.
   *
   * Do NOT treat this as a permanent payment failure.
   */
}

/*
 * ============================================================
 * INVOICE FINALIZATION FAILED
 * ============================================================
 */

export async function handleInvoiceFinalizationFailed(invoice: Stripe.Invoice) {
  const stripeSubscriptionId = extractSubscriptionId(invoice);

  if (stripeSubscriptionId) {
    /*
     * Only attempt subscription synchronization when this
     * invoice belongs to a subscription.
     */
    await ensureLocalSubscriptionForInvoice(invoice);

    const stripeSubscription =
      await stripeService.stripe.subscriptions.retrieve(stripeSubscriptionId);

    await syncSubscriptionFromStripe(stripeSubscription);
  }

  const failureReason =
    invoice.last_finalization_error?.message ??
    invoice.last_finalization_error?.code ??
    "Invoice finalization failed";

  console.error(
    `[Stripe][Invoice Finalization Failed]` +
      ` | invoice=${invoice.id}` +
      ` | subscription=${stripeSubscriptionId ?? "none"}` +
      ` | reason=${failureReason}`
  );

  /*
   * IMPORTANT:
   *
   * This is NOT a payment failure.
   * Stripe could not finalize the invoice, so payment
   * collection may not even have been attempted.
   *
   * Notify admin/customer depending on your application.
   */
}

/*
 * ============================================================
 * SUBSCRIPTION SCHEDULE TERMINATED
 * ============================================================
 */

export async function handleSubscriptionScheduleEnded(
  schedule: Stripe.SubscriptionSchedule
) {
  const rawSchedule = schedule as unknown as Record<string, any>;

  /*
   * released_subscription is important for
   * subscription_schedule.released.
   */
  const rawSubscription =
    rawSchedule.released_subscription ?? rawSchedule.subscription;

  let stripeSubscriptionId: string | null = null;

  if (typeof rawSubscription === "string") {
    stripeSubscriptionId = rawSubscription;
  } else if (rawSubscription?.id) {
    stripeSubscriptionId = rawSubscription.id;
  }

  if (!stripeSubscriptionId) {
    console.warn(
      `[Stripe] Subscription schedule ${schedule.id} ended ` +
        `without a resolvable subscription ID`
    );

    return;
  }

  const localSubscription =
    await subscriptionRepo.getSubscriptionByPaymentProviderId(
      stripeSubscriptionId
    );

  if (!localSubscription) {
    console.warn(
      `[Stripe] Subscription schedule ${schedule.id} ended, ` +
        `but local subscription ${stripeSubscriptionId} was not found`
    );

    return;
  }

  /*
   * NOW it is safe to clear local pending schedule data.
   */
  await subscriptionRepo.updateSubscription(localSubscription.id, {
    scheduledPlanId: null,
    scheduledBillingPeriod: null
  });

  console.info(
    `[Stripe] Cleared completed schedule state for ` +
      `subscription ${stripeSubscriptionId}`
  );
}
