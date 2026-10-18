import { prisma } from "../../../config/database.js";

/*
 * ============================================================================
 * INVOICE REPOSITORY
 * ============================================================================
 *
 * Repository responsibilities:
 *
 * - Query the database
 * - Return persisted records
 *
 * It should NOT:
 *
 * - Format Stripe amounts
 * - Determine recurring vs initial payment
 * - Build frontend DTOs
 * - Apply presentation/business rules
 */

export const invoiceRepo = {
  /**
   * Returns successful Stripe invoice-payment webhook events
   * for a specific Stripe subscription.
   *
   * IMPORTANT:
   *
   * We query `invoice.payment_succeeded` instead of `invoice.paid`
   * because this repository is being used for actual successful
   * payment history.
   *
   * Zero-value invoices are intentionally NOT filtered here.
   * That is business logic and belongs in the service layer.
   */
  getPaymentEventsBySubscriptionId: async (stripeSubscriptionId: string) => {
    return prisma.payment_providerWebhookEvent.findMany({
      where: {
        eventType: "invoice.payment_succeeded",

        /*
         * Do NOT filter by processed.
         *
         * This returns both:
         * processed = true
         * processed = false
         */

        OR: [
          /*
           * ==================================================
           * NEWER STRIPE INVOICE STRUCTURE
           * ==================================================
           */

          {
            payload: {
              path: [
                "data",
                "object",
                "parent",
                "subscription_details",
                "subscription"
              ],
              equals: stripeSubscriptionId
            }
          },

          {
            payload: {
              path: [
                "data",
                "object",
                "parent",
                "subscription_details",
                "subscription",
                "id"
              ],
              equals: stripeSubscriptionId
            }
          },

          /*
           * ==================================================
           * ALTERNATIVE / TRANSITIONAL STRUCTURE
           * ==================================================
           */

          {
            payload: {
              path: ["data", "object", "subscription_details", "subscription"],
              equals: stripeSubscriptionId
            }
          },

          {
            payload: {
              path: [
                "data",
                "object",
                "subscription_details",
                "subscription",
                "id"
              ],
              equals: stripeSubscriptionId
            }
          },

          /*
           * ==================================================
           * LEGACY STRIPE STRUCTURE
           * ==================================================
           */

          {
            payload: {
              path: ["data", "object", "subscription"],
              equals: stripeSubscriptionId
            }
          },

          {
            payload: {
              path: ["data", "object", "subscription", "id"],
              equals: stripeSubscriptionId
            }
          }
        ]
      },

      orderBy: {
        createdAt: "desc"
      }
    });
  }
};
