import Stripe from "stripe";
import webhookRepo from "../../../repo/webhook.repo.js";
import { ServiceResult } from "../../../service/plans.service.js";
import {
  handleCheckoutSessionCompleted,
  handleInvoicePaid,
  handleInvoicePaymentFailed,
  handleSubscriptionDeleted,
  handleSubscriptionUpdated
} from "../../../../../utils/webhook handlers.js";

export function mapStripeSubscriptionStatus(
  status: Stripe.Subscription.Status
): string {
  switch (status) {
    case "trialing":
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
    default:
      return "pending";
  }
}
export async function webhookService(
  event: Stripe.Event
): Promise<ServiceResult<{ duplicate: boolean }>> {
  const existingAudit = await webhookRepo.getWebhookEventByProviderId(event.id);

  if (existingAudit && existingAudit.processed) {
    console.info(
      `[Audit] Duplicate webhook event skipped: ${event.type} (${event.id})`
    );
    return { success: true, data: { duplicate: true } };
  }

  const auditedEvent =
    existingAudit ?? (await webhookRepo.createWebhookEvent(event));

  try {
    switch (event.type) {
      case "checkout.session.completed":
        await handleCheckoutSessionCompleted(
          event.data.object as Stripe.Checkout.Session
        );
        break;
      case "customer.subscription.updated":
        await handleSubscriptionUpdated(
          event.data.object as Stripe.Subscription
        );
        break;
      case "customer.subscription.deleted":
        await handleSubscriptionDeleted(
          event.data.object as Stripe.Subscription
        );
        break;
      case "invoice.paid":
        await handleInvoicePaid(event.data.object as Stripe.Invoice);
        break;
      case "invoice.payment_failed":
        await handleInvoicePaymentFailed(event.data.object as Stripe.Invoice);
        break;
      default:
        console.info(
          `[Audit] Unhandled event received & audited: ${event.type} (${event.id})`
        );
        break;
    }

    await webhookRepo.markWebhookEventProcessed(auditedEvent.id);
    return { success: true, data: { duplicate: false } };
  } catch (error: any) {
    console.error(
      `[Webhook Error] Processing failed for event ${event.type} (${event.id}):`,
      error
    );
    return {
      success: false,
      code: "WEBHOOK_PROCESSING_ERROR",
      message: error.message || "An error occurred while processing the webhook"
    };
  }
}
