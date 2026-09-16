import Stripe from "stripe";
import subscriptionRepo from "../../../repo/subscription.repo.js";
import webhookRepo from "../../../repo/webhook.repo.js";
import planRepo from "../../../repo/plans.repo.js";
import { Plan, Subscription } from "../../../../../generated/prisma/client.js";

import { stripeService } from "./stripeService.js";
const tenantId = "d41eeac6-a61a-44c2-85c1-93d39a69b025";

function mapStripeSubscriptionStatus(
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
export async function webhookService(event: Stripe.Event) {
  // 1. Idempotency Check: Don't re-process completed events
  const existingAudit = await webhookRepo.getWebhookEventByProviderId(event.id);
  if (existingAudit && existingAudit.processed) {
    console.info(
      `[Audit] Duplicate webhook event skipped: ${event.type} (${event.id})`
    );
    return { success: true, duplicate: true };
  }

  // 2. Audit every incoming event immediately into payment_provider_webhook_events
  const auditedEvent =
    existingAudit ?? (await webhookRepo.createWebhookEvent(event));

  try {
    switch (event.type) {
      // ==========================================
      // CHECKOUT COMPLETED (Initial Setup)
      // ==========================================
      case "checkout.session.completed": {
        const session = event.data.object as Stripe.Checkout.Session;

        if (!session.subscription) {
          console.warn(
            `[Audit] Checkout session ${session.id} finished without subscription ID`
          );
          break;
        }

        const stripeSubId =
          typeof session.subscription === "string"
            ? session.subscription
            : session.subscription.id;

        const existingSub =
          await subscriptionRepo.getSubscriptionByPaymentProviderId(
            stripeSubId
          );
        if (!existingSub) {
          await insertSubscriptionWrapper(stripeSubId, tenantId);
        }
        break;
      }

      // ==========================================
      // SUBSCRIPTION UPDATED (Renewals, Trials ending, Plan changes)
      // ==========================================
      case "customer.subscription.updated": {
        const subscription = event.data.object as Stripe.Subscription;

        const currentSubscription =
          await subscriptionRepo.getSubscriptionByPaymentProviderId(
            subscription.id
          );
        if (!currentSubscription) {
          throw new Error(
            `Subscription not found for paymentProviderSubscriptionId: ${subscription.id}`
          );
        }

        const item = subscription.items.data[0];
        if (!item) {
          throw new Error(
            `No items found in Stripe subscription: ${subscription.id}`
          );
        }

        const plan = await planRepo.getPlanByPriceId(item.price.id);
        if (!plan) {
          throw new Error(`Plan not found for Stripe Price: ${item.price.id}`);
        }

        await subscriptionRepo.updateSubscription(currentSubscription.id, {
          planId: plan.id,
          status: mapStripeSubscriptionStatus(subscription.status),
          currentPeriodStart: new Date(item.current_period_start * 1000),
          currentPeriodEnd: new Date(item.current_period_end * 1000),
          cancelAtPeriodEnd: subscription.cancel_at_period_end,
          cancelledAt: subscription.canceled_at
            ? new Date(subscription.canceled_at * 1000)
            : null
        });
        break;
      }

      // ==========================================
      // SUBSCRIPTION DELETED (Cancelled / Terminated)
      // ==========================================
      case "customer.subscription.deleted": {
        const stripeSubscription = event.data.object as Stripe.Subscription;

        const currentSubscription =
          await subscriptionRepo.getSubscriptionByPaymentProviderId(
            stripeSubscription.id
          );
        if (!currentSubscription) {
          throw new Error(
            `Subscription not found for deletion: ${stripeSubscription.id}`
          );
        }

        await subscriptionRepo.updateSubscription(currentSubscription.id, {
          status: mapStripeSubscriptionStatus(stripeSubscription.status),
          cancelAtPeriodEnd: false
        });
        break;
      }

      // ==========================================
      // INVOICE PAID (Successful Recurring Payments)
      // ==========================================
      case "invoice.paid": {
        const invoice = event.data.object as Stripe.Invoice;
        const stripeSubscriptionId = extractSubscriptionId(invoice);

        if (!stripeSubscriptionId) {
          console.warn(
            `[Audit] Invoice ${invoice.id} paid without subscription.`
          );
          break;
        }

        let subscription =
          await subscriptionRepo.getSubscriptionByPaymentProviderId(
            stripeSubscriptionId
          );
        if (!subscription) {
          subscription = await insertSubscriptionWrapper(
            stripeSubscriptionId,
            tenantId
          );
        }

        await webhookRepo.createInvoicePayment(
          invoice,
          subscription.id,
          "succeeded"
        );
        break;
      }

      // ==========================================
      // INVOICE PAYMENT FAILED (Dunning / Insufficient Funds)
      // ==========================================
      // ==========================================
      // INVOICE PAYMENT FAILED (Dunning / Insufficient Funds)
      // ==========================================
      case "invoice.payment_failed": {
        const invoice = event.data.object as Stripe.Invoice;
        const stripeSubscriptionId = extractSubscriptionId(invoice);

        if (!stripeSubscriptionId) {
          console.warn(
            `[Audit] Invoice ${invoice.id} payment failed without subscription.`
          );
          break;
        }

        let subscription =
          await subscriptionRepo.getSubscriptionByPaymentProviderId(
            stripeSubscriptionId
          );
        if (!subscription) {
          subscription = await insertSubscriptionWrapper(
            stripeSubscriptionId,
            tenantId
          );
        }

        await subscriptionRepo.updateSubscription(subscription.id, {
          status: "past_due"
        });

        // 1. Resolve actual decline reason from PaymentIntent or Invoice error
        let failureReason: string | null =
          invoice.last_finalization_error?.message ?? null;

        const paymentIntentId = extractPaymentIntentId(invoice);

        if (!failureReason && paymentIntentId) {
          try {
            const paymentIntent =
              await stripeService.stripe.paymentIntents.retrieve(
                paymentIntentId
              );
            failureReason =
              paymentIntent.last_payment_error?.message ??
              paymentIntent.last_payment_error?.decline_code ??
              null;
          } catch (err) {
            console.warn(
              `[Audit] Could not retrieve PaymentIntent ${paymentIntentId} for decline reason:`,
              err
            );
          }
        }

        // 2. Fallback only if Stripe returned no error payload at all
        if (!failureReason) {
          failureReason =
            "Payment collection failed (card declined or insufficient funds)";
        }

        await webhookRepo.createInvoicePayment(
          invoice,
          subscription.id,
          "failed",
          failureReason
        );
        break;
      }

      // ==========================================
      // ALL OTHER UNHANDLED EVENTS
      // ==========================================
      default: {
        console.info(
          `[Audit] Unhandled event received & audited: ${event.type} (${event.id})`
        );
        break;
      }
    }

    // 3. Acknowledge and mark event as processed
    await webhookRepo.markWebhookEventProcessed(auditedEvent.id);
    return { success: true };
  } catch (error) {
    // Left unflagged (processed: false) to allow triage and retries
    console.error(
      `[Webhook Error] Processing failed for event ${event.type} (${event.id}):`,
      error
    );
    throw error;
  }
}
function extractSubscriptionId(invoice: Stripe.Invoice): string | null {
  const inv = invoice as Record<string, any>;

  // 1. Current Stripe API versions: subscription_details
  if (typeof inv.subscription_details?.subscription === "string") {
    return inv.subscription_details.subscription;
  }
  if (inv.subscription_details?.subscription?.id) {
    return inv.subscription_details.subscription.id;
  }

  // 2. Newer Stripe API versions: parent -> subscription_details
  if (typeof inv.parent?.subscription_details?.subscription === "string") {
    return inv.parent.subscription_details.subscription;
  }
  if (inv.parent?.subscription_details?.subscription?.id) {
    return inv.parent.subscription_details.subscription.id;
  }

  // 3. Legacy Stripe API versions: top-level subscription
  if (typeof inv.subscription === "string") {
    return inv.subscription;
  }
  if (inv.subscription?.id) {
    return inv.subscription.id;
  }

  return null;
}

async function insertSubscriptionWrapper(
  subscriptionId: string,
  targetTenantId: string
): Promise<Subscription> {
  const subscription =
    await stripeService.stripe.subscriptions.retrieve(subscriptionId);
  const item = subscription.items.data[0];
  if (!item) {
    throw new Error(`Stripe subscription ${subscriptionId} has no items`);
  }

  const priceId = item.price.id;
  const plan = (await planRepo.getPlanByPriceId(priceId)) as Plan;
  if (!plan) {
    throw new Error(`Local plan not found for Stripe Price ID: ${priceId}`);
  }

  return await subscriptionRepo.createSubscription({
    tenantId: targetTenantId,
    plan: {
      connect: {
        id: plan.id
      }
    },
    paymentProvider: "stripe",
    paymentProviderCustomerId: subscription.customer as string,
    currentPeriodStart: new Date(item.current_period_start * 1000),
    currentPeriodEnd: new Date(item.current_period_end * 1000),
    paymentProviderSubscriptionId: subscription.id,
    status: mapStripeSubscriptionStatus(subscription.status),
    cancelAtPeriodEnd: subscription.cancel_at_period_end,
    cancelledAt: subscription.canceled_at
      ? new Date(subscription.canceled_at * 1000)
      : null
  });
}
function extractPaymentIntentId(invoice: Stripe.Invoice): string | null {
  const inv = invoice as Record<string, any>;
  if (typeof inv.payment_intent === "string") return inv.payment_intent;
  if (inv.payment_intent?.id) return inv.payment_intent.id;
  if (typeof inv.payments?.data?.[0]?.payment_intent === "string") {
    return inv.payments.data[0].payment_intent;
  }
  return null;
}
