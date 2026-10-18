import type { Prisma } from "../../generated/prisma/client.js";
import { TENANT_NOTIFICATION_EVENTS } from "./tenant-notification.types.js";

type CustomPlanOfferReadyArgs = {
  tenantId: string;
  quoteId: string;
  quoteName: string;
  expiresAt: Date | null;
};

async function customPlanOfferReady(
  tx: Prisma.TransactionClient,
  args: CustomPlanOfferReadyArgs
): Promise<void> {
  const quoteId = args.quoteId?.trim();

  if (!quoteId) {
    throw new Error("CUSTOM_PLAN_OFFER_READY notification requires quoteId");
  }

  const dedupeKey = `custom-plan:offer-ready:${quoteId}`;

  await tx.tenantNotificationOutbox.createMany({
    data: [
      {
        tenantId: args.tenantId,
        eventType: TENANT_NOTIFICATION_EVENTS.CUSTOM_PLAN_OFFER_READY,
        dedupeKey,
        payload: {
          quoteId,
          quoteName: args.quoteName,
          expiresAt: args.expiresAt?.toISOString() ?? null
        } as Prisma.InputJsonObject,
        occurredAt: new Date()
      }
    ],
    skipDuplicates: true
  });
}

export const tenantNotificationProducer = {
  customPlanOfferReady
};
