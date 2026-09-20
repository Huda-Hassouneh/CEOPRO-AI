import Stripe from "stripe";

import webhookRepo from "../../../repo/webhook.repo.js";
import { ServiceResult } from "../../../service/plans.service.js";

import {
  handleCheckoutSessionCompleted,
  handleInvoiceFinalizationFailed,
  handleInvoicePaid,
  handleInvoicePaymentActionRequired,
  handleInvoicePaymentFailed,
  handleInvoicePaymentSucceeded,
  handleSubscriptionCreated,
  handleSubscriptionDeleted,
  handleSubscriptionScheduleEnded,
  handleSubscriptionTrialWillEnd,
  handleSubscriptionUpdated
} from "../../../../../utils/webhook handlers.js";

/*
 * Re-exported to avoid breaking any existing imports elsewhere
 * in your codebase.
 *
 * The implementation itself now lives in utils/webhook.ts,
 * which removes the previous circular dependency:
 *
 * webhook.service
 *   -> webhook handlers
 *      -> webhook helper
 *         -> webhook.service   ❌ old
 */
export { mapStripeSubscriptionStatus } from "../../../../../utils/webhook.js";

export async function webhookService(
  event: Stripe.Event
): Promise<ServiceResult<{ duplicate: boolean }>> {
  /*
   * EVENT-LEVEL IDEMPOTENCY
   *
   * Stripe can deliver the same event more than once.
   *
   * IMPORTANT:
   * providerEventId should ALSO have a UNIQUE constraint
   * in the database. The SELECT here alone does not protect
   * against two concurrent webhook requests.
   */
  const existingAudit = await webhookRepo.getWebhookEventByProviderId(event.id);

  if (existingAudit?.processed) {
    console.info(
      `[Stripe][Webhook] Duplicate event skipped: ${event.type} (${event.id})`
    );

    return {
      success: true,
      data: {
        duplicate: true
      }
    };
  }

  const auditedEvent =
    existingAudit ?? (await webhookRepo.createWebhookEvent(event));

  try {
    switch (event.type) {
      /*
       * =====================================================
       * CHECKOUT
       * =====================================================
       */

      case "checkout.session.completed": {
        await handleCheckoutSessionCompleted(
          event.data.object as Stripe.Checkout.Session
        );

        break;
      }

      /*
       * =====================================================
       * SUBSCRIPTION LIFECYCLE
       * =====================================================
       */

      case "customer.subscription.created": {
        await handleSubscriptionCreated(
          event.data.object as Stripe.Subscription
        );

        break;
      }

      case "customer.subscription.updated":
      case "customer.subscription.paused":
      case "customer.subscription.resumed": {
        await handleSubscriptionUpdated(
          event.data.object as Stripe.Subscription
        );

        break;
      }

      case "customer.subscription.deleted": {
        await handleSubscriptionDeleted(
          event.data.object as Stripe.Subscription
        );

        break;
      }

      case "customer.subscription.trial_will_end": {
        await handleSubscriptionTrialWillEnd(
          event.data.object as Stripe.Subscription
        );

        break;
      }

      /*
       * =====================================================
       * INVOICE / PAYMENT LIFECYCLE
       * =====================================================
       */

      /*
       * Invoice is settled.
       *
       * IMPORTANT:
       * invoice.paid does NOT necessarily mean that Stripe
       * collected money. It can also be marked paid
       * out-of-band.
       *
       * Therefore:
       * - synchronize subscription
       * - process invoice-related business logic
       * - DO NOT blindly record a monetary transaction here
       */
      case "invoice.paid": {
        await handleInvoicePaid(event.data.object as Stripe.Invoice);

        break;
      }

      /*
       * Actual invoice payment attempt succeeded.
       *
       * This is where we record a successful real payment,
       * provided amount_paid > 0.
       */
      case "invoice.payment_succeeded": {
        await handleInvoicePaymentSucceeded(
          event.data.object as Stripe.Invoice
        );

        break;
      }

      /*
       * Actual payment attempt failed.
       */
      case "invoice.payment_failed": {
        await handleInvoicePaymentFailed(event.data.object as Stripe.Invoice);

        break;
      }

      /*
       * Usually SCA / 3DS / customer authentication.
       */
      case "invoice.payment_action_required": {
        await handleInvoicePaymentActionRequired(
          event.data.object as Stripe.Invoice
        );

        break;
      }

      /*
       * Invoice could not even be finalized,
       * therefore Stripe cannot collect it.
       */
      case "invoice.finalization_failed": {
        await handleInvoiceFinalizationFailed(
          event.data.object as Stripe.Invoice
        );

        break;
      }

      /*
       * =====================================================
       * SUBSCRIPTION SCHEDULE TERMINAL EVENTS
       * =====================================================
       *
       * We DON'T clear scheduledPlanId every time a
       * customer.subscription.updated event arrives.
       *
       * We clear the scheduled local state only when the
       * actual Stripe schedule reaches a terminal state.
       */

      case "subscription_schedule.released":
      case "subscription_schedule.completed":
      case "subscription_schedule.canceled":
      case "subscription_schedule.aborted": {
        await handleSubscriptionScheduleEnded(
          event.data.object as Stripe.SubscriptionSchedule
        );

        break;
      }

      /*
       * =====================================================
       * EVERYTHING ELSE
       * =====================================================
       */

      default: {
        console.info(
          `[Stripe][Webhook] Unhandled event received and audited: ` +
            `${event.type} (${event.id})`
        );

        break;
      }
    }

    /*
     * Only mark the webhook processed AFTER all business
     * logic completed successfully.
     */
    await webhookRepo.markWebhookEventProcessed(auditedEvent.id);

    return {
      success: true,
      data: {
        duplicate: false
      }
    };
  } catch (error: any) {
    console.error(
      `[Stripe][Webhook Error] Processing failed for ` +
        `${event.type} (${event.id}):`,
      error
    );

    /*
     * DO NOT mark it processed.
     *
     * Your controller should return a non-2xx response
     * when success === false if you want Stripe to retry.
     */
    return {
      success: false,
      code: "WEBHOOK_PROCESSING_ERROR",
      message:
        error?.message ||
        "An error occurred while processing the Stripe webhook"
    };
  }
}
