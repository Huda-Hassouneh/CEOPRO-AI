import type { Prisma } from "../../generated/prisma/client.js";
import { PLATFORM_NOTIFICATION_EVENTS } from "./platform-notification.types.js";

type PaymentFailedArgs = {
  tenantId: string;
  subscriptionId: string;
  stripeEventId: string;
  stripeInvoiceId: string;
  paymentIntentId: string | null;
  failureReason: string;
};

async function paymentFailed(
  tx: Prisma.TransactionClient,
  args: PaymentFailedArgs
): Promise<void> {
  const stripeEventId = args.stripeEventId?.trim();

  if (!stripeEventId) {
    throw new Error("PAYMENT_FAILED notification requires stripeEventId");
  }

  const dedupeKey = `stripe:payment_failed:${stripeEventId}`;

  await tx.platformNotificationOutbox.upsert({
    where: {
      tenantId_dedupeKey: {
        tenantId: args.tenantId,
        dedupeKey
      }
    },
    update: {},
    create: {
      tenantId: args.tenantId,
      eventType: PLATFORM_NOTIFICATION_EVENTS.PAYMENT_FAILED,
      dedupeKey,
      payload: {
        subscriptionId: args.subscriptionId,
        stripeEventId,
        stripeInvoiceId: args.stripeInvoiceId,
        paymentIntentId: args.paymentIntentId,
        failureReason: args.failureReason
      } as Prisma.InputJsonObject,
      occurredAt: new Date()
    }
  });
}

export const platformNotificationProducer = {
  paymentFailed
};
