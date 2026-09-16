import Stripe from "stripe";
import { prisma } from "../../../config/database.js";
import { Prisma } from "../../../generated/prisma/client.js";

async function createWebhookEvent(event: Stripe.Event) {
  return prisma.payment_providerWebhookEvent.create({
    data: {
      payment_providerEventId: event.id,
      eventType: event.type,
      processed: false,
      payload: event as unknown as Prisma.InputJsonValue
    }
  });
}
async function createInvoicePayment(
  invoice: any,
  subscriptionId: string,
  status: "succeeded" | "failed" | "pending" = "succeeded",
  failureReason: string | null = null
) {
  const rawAmount =
    status === "failed" ? invoice.amount_due : invoice.amount_paid;
  const amount = rawAmount / 100;

  const paymentIntentId =
    typeof invoice.payment_intent === "string"
      ? invoice.payment_intent
      : (invoice.payment_intent?.id ?? null);

  return prisma.paymentTransaction.create({
    data: {
      subscriptionId,
      payment_providerInvoiceId: invoice.id,
      payment_providerPaymentIntentId: paymentIntentId,
      amount,
      currency: invoice.currency.toUpperCase(),
      status,
      failureReason,
      paidAt:
        status === "succeeded"
          ? invoice.status_transitions?.paid_at
            ? new Date(invoice.status_transitions.paid_at * 1000)
            : new Date()
          : null
    }
  });
}
async function markWebhookEventProcessed(webhookEventId: string) {
  return prisma.payment_providerWebhookEvent.update({
    where: {
      id: webhookEventId
    },
    data: {
      processed: true,
      processedAt: new Date()
    }
  });
}
async function getWebhookEventByProviderId(payment_providerEventId: string) {
  return prisma.payment_providerWebhookEvent.findUnique({
    where: { payment_providerEventId }
  });
}
export default {
  createWebhookEvent,
  createInvoicePayment,
  markWebhookEventProcessed,
  getWebhookEventByProviderId
};
