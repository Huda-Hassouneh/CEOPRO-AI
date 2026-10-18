import { invoiceRepo } from "../repo/invoice.repo.js";
import subscriptionRepo from "../repo/subscription.repo.js";
import { fromStripeMinorUnits } from "../../../utils/currency.js";
import type { ServiceResult } from "../../../types/service.js";

/*
 * ============================================================================
 * TYPES
 * ============================================================================
 */

export type TenantInvoiceDto = {
  id: string;

  invoiceNumber: string | null;

  date: string | null;

  amount: number;

  amountMinor: number;

  currency: string;

  status: string | null;

  type: "initial" | "recurring" | "subscription_change" | "threshold" | "other";

  billingReason: string | null;

  periodStart: string | null;

  periodEnd: string | null;

  pdfUrl: string | null;

  hostedUrl: string | null;
};

type InvoiceServiceResult = ServiceResult<TenantInvoiceDto[]>;

/*
 * ============================================================================
 * STRIPE AMOUNT HELPERS
 * ============================================================================
 *
 * Stripe sends amounts in the currency's minor unit.
 *
 * Most currencies:
 *
 * 2900 => 29.00
 *
 * Some currencies such as JPY are zero-decimal.
 *
 * Stripe documents which currencies are zero-decimal.
 */

/*
 * ============================================================================
 * INVOICE CLASSIFICATION
 * ============================================================================
 */

function classifyInvoice(
  billingReason?: string | null
): TenantInvoiceDto["type"] {
  switch (billingReason) {
    case "subscription_create":
      return "initial";

    case "subscription_cycle":
      return "recurring";

    case "subscription_update":
      return "subscription_change";

    case "subscription_threshold":
      return "threshold";

    default:
      return "other";
  }
}

/*
 * ============================================================================
 * UNIX DATE HELPER
 * ============================================================================
 */

function unixToIso(timestamp?: number | null): string | null {
  if (typeof timestamp !== "number") {
    return null;
  }

  return new Date(timestamp * 1000).toISOString();
}

/*
 * ============================================================================
 * GET TENANT INVOICES
 * ============================================================================
 */

export async function getTenantInvoicesService(
  tenantId: string
): Promise<InvoiceServiceResult> {
  try {
    /*
     * ========================================================
     * 1. FIND CURRENT SUBSCRIPTION
     * ========================================================
     */

    const subscription =
      await subscriptionRepo.getCurrentSubscriptionByTenant(tenantId);

    if (!subscription || !subscription.paymentProviderSubscriptionId) {
      return {
        success: true,
        data: []
      };
    }

    const stripeSubscriptionId = subscription.paymentProviderSubscriptionId;

    /*
     * ========================================================
     * 2. FETCH PAYMENT EVENTS
     * ========================================================
     *
     * Repository should return BOTH:
     *
     * - invoice.payment_succeeded
     * - invoice.payment_failed
     *
     * And should NOT filter by processed=true.
     */

    const records =
      await invoiceRepo.getPaymentEventsBySubscriptionId(stripeSubscriptionId);

    console.log("[Billing History] Stripe subscription:", stripeSubscriptionId);

    console.log("[Billing History] Payment events found:", records.length);

    /*
     * ========================================================
     * 3. BUILD PAYMENT HISTORY
     * ========================================================
     *
     * IMPORTANT:
     *
     * We deliberately DO NOT deduplicate by invoice.id.
     *
     * Example:
     *
     * invoice.payment_failed
     *        ↓
     * Stripe retries
     *        ↓
     * invoice.payment_succeeded
     *
     * Both should be returned to the frontend.
     */

    const invoices: TenantInvoiceDto[] = [];

    for (const record of records) {
      const event = record.payload as any;

      /*
       * Prefer the actual Stripe Event type.
       *
       * Fall back to the DB eventType column.
       */
      const eventType = event?.type ?? record.eventType;

      console.log("[Billing History] Processing event:", {
        eventType,
        processed: record.processed,
        eventId: event?.id
      });

      /*
       * Only payment-attempt events belong in this history.
       */
      const isSucceeded = eventType === "invoice.payment_succeeded";

      const isFailed = eventType === "invoice.payment_failed";

      if (!isSucceeded && !isFailed) {
        console.log("[Billing History] Unsupported event skipped:", eventType);

        continue;
      }

      /*
       * Your payload contains the complete Stripe Event,
       * therefore the invoice is here:
       *
       * event.data.object
       */
      const invoice = event?.data?.object;

      if (!invoice?.id) {
        console.warn(
          "[Billing History] Event has no invoice object:",
          event?.id
        );

        continue;
      }

      /*
       * =====================================================
       * 4. DETERMINE PAYMENT AMOUNT
       * =====================================================
       *
       * Successful attempt:
       *   amount_paid
       *
       * Failed attempt:
       *   amount_paid is usually 0, therefore use the amount
       *   Stripe attempted to collect.
       */

      let rawAmount: number;

      if (isSucceeded) {
        rawAmount = Number(
          invoice.amount_paid ?? invoice.amount_due ?? invoice.total ?? 0
        );
      } else {
        rawAmount = Number(
          invoice.amount_due ?? invoice.amount_remaining ?? invoice.total ?? 0
        );
      }

      if (!Number.isFinite(rawAmount) || rawAmount <= 0) {
        console.log("[Billing History] Zero-value invoice skipped:", {
          eventId: event?.id,
          invoiceId: invoice.id,
          eventType,
          amountPaid: invoice.amount_paid,
          amountDue: invoice.amount_due,
          amountRemaining: invoice.amount_remaining,
          total: invoice.total
        });

        /*
         * Ignore free-trial / zero-dollar invoices.
         */
        continue;
      }

      /*
       * =====================================================
       * 5. NORMALIZE CURRENCY
       * =====================================================
       */

      const currency =
        typeof invoice.currency === "string"
          ? invoice.currency.toLowerCase()
          : "";

      /*
       * =====================================================
       * 6. BILLING REASON
       * =====================================================
       */

      const billingReason =
        typeof invoice.billing_reason === "string"
          ? invoice.billing_reason
          : null;

      /*
       * =====================================================
       * 7. PERIOD
       * =====================================================
       */

      const periodStart = unixToIso(invoice.period_start);

      const periodEnd = unixToIso(invoice.period_end);

      /*
       * =====================================================
       * 8. EVENT / PAYMENT DATE
       * =====================================================
       *
       * Prefer the Stripe EVENT date because we're displaying
       * payment attempts.
       *
       * If unavailable, fall back to invoice creation.
       */

      const date =
        typeof event?.created === "number"
          ? unixToIso(event.created)
          : unixToIso(invoice.created);

      /*
       * =====================================================
       * 9. BUILD DTO
       * =====================================================
       *
       * IMPORTANT:
       *
       * invoice.status and payment result are different.
       *
       * Failed payment:
       *
       * invoice.status = "open"
       * payment result  = "failed"
       *
       * Successful payment:
       *
       * invoice.status = "paid"
       * payment result  = "paid"
       */

      const dto: TenantInvoiceDto = {
        /*
         * Keep invoice ID here so existing frontend/download
         * functionality does not break.
         */
        id: invoice.id,

        invoiceNumber: invoice.number ?? null,

        date,

        amount: fromStripeMinorUnits(rawAmount, currency),

        amountMinor: rawAmount,

        currency,

        /*
         * Frontend payment result.
         */
        status: isSucceeded ? "paid" : "failed",

        type: classifyInvoice(billingReason),

        billingReason,

        periodStart,

        periodEnd,

        pdfUrl: invoice.invoice_pdf ?? null,

        hostedUrl: invoice.hosted_invoice_url ?? null
      };

      console.log("[Billing History] Adding payment:", {
        stripeEventId: event?.id,
        invoiceId: invoice.id,
        eventType,
        status: dto.status,
        amount: dto.amount,
        processed: record.processed
      });

      /*
       * IMPORTANT:
       *
       * Push EVERY payment attempt.
       *
       * Do NOT use:
       *
       * seenInvoiceIds
       *
       * or:
       *
       * invoiceMap.set(invoice.id, ...)
       *
       * because that would remove previous failed attempts.
       */
      invoices.push(dto);
    }

    /*
     * ========================================================
     * 10. SORT NEWEST FIRST
     * ========================================================
     */

    invoices.sort((a, b) => {
      const aTime = a.date ? new Date(a.date).getTime() : 0;

      const bTime = b.date ? new Date(b.date).getTime() : 0;

      return bTime - aTime;
    });

    console.log("[Billing History] Final response count:", invoices.length);

    return {
      success: true,
      data: invoices
    };
  } catch (error: any) {
    console.error("[Get Tenant Invoices Error]:", error);

    return {
      success: false,
      code: "INTERNAL_SERVER_ERROR",
      message: "Failed to retrieve billing history."
    };
  }
}
