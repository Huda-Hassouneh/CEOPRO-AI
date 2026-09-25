import Stripe from "stripe";
import { prisma } from "../../../config/database.js";
import { Prisma } from "../../../generated/prisma/client.js";
import { fromStripeMinorUnits } from "../../../utils/currency.js";
import { resolvePaymentIntentId } from "../../../utils/webhook.js";

async function createWebhookEvent(event: Stripe.Event) {
  return prisma.payment_providerWebhookEvent.upsert({
    where: { payment_providerEventId: event.id },
    update: {},
    create: {
      payment_providerEventId: event.id,
      eventType: event.type,
      processed: false,
      payload: event as unknown as Prisma.InputJsonValue
    }
  });
}

async function createInvoicePayment(
  invoice: Stripe.Invoice,
  subscriptionId: string,
  status: "succeeded" | "failed" | "pending" = "succeeded",
  failureReason: string | null = null
) {
  const rawAmount = status === "failed" ? invoice.amount_due : invoice.amount_paid;
  const paymentIntentId = await resolvePaymentIntentId(invoice);
  const idempotencyKey = `stripe:invoice:${invoice.id}`;
  const paidAt = status === "succeeded"
    ? invoice.status_transitions?.paid_at
      ? new Date(invoice.status_transitions.paid_at * 1000)
      : new Date()
    : null;

  return prisma.paymentTransaction.upsert({
    where: { idempotencyKey },
    update: {
      subscriptionId,
      payment_providerInvoiceId: invoice.id,
      payment_providerPaymentIntentId: paymentIntentId,
      amount: fromStripeMinorUnits(rawAmount, invoice.currency),
      currency: invoice.currency.toUpperCase(),
      status,
      failureReason,
      paidAt
    },
    create: {
      idempotencyKey,
      subscriptionId,
      payment_providerInvoiceId: invoice.id,
      payment_providerPaymentIntentId: paymentIntentId,
      amount: fromStripeMinorUnits(rawAmount, invoice.currency),
      currency: invoice.currency.toUpperCase(),
      status,
      failureReason,
      paidAt
    }
  });
}

async function markWebhookEventProcessed(webhookEventId: string) {
  return prisma.payment_providerWebhookEvent.update({
    where: { id: webhookEventId },
    data: { processed: true, processedAt: new Date() }
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
