import { prisma } from "../../../config/database.js";

export const invoiceRepo = {
  /**
   * Fetches all paid invoice events for a specific Stripe subscription
   */
  getPaidInvoicesBySubscriptionId: async (stripeSubscriptionId: string) => {
    return await prisma.payment_providerWebhookEvent.findMany({
      where: {
        eventType: "invoice.paid",
        payload: {
          path: ["data", "object", "subscription"],
          equals: stripeSubscriptionId
        }
      },
      orderBy: {
        createdAt: "desc"
      }
    });
  }
};
