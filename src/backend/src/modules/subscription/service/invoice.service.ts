import { invoiceRepo } from "../repo/invoice.repo.js";
import subscriptionRepo from "../repo/subscription.repo.js";

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

type InvoiceServiceResult =
  | {
      success: true;
      data: TenantInvoiceDto[];
    }
  | {
      success: false;
      code: string;
      message: string;
    };

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

const STRIPE_ZERO_DECIMAL_CURRENCIES = new Set([
  "bif",
  "clp",
  "djf",
  "gnf",
  "jpy",
  "kmf",
  "krw",
  "mga",
  "pyg",
  "rwf",
  "ugx",
  "vnd",
  "vuv",
  "xaf",
  "xof",
  "xpf"
]);

/**
 * Converts Stripe minor-unit amount into a normal decimal amount.
 *
 * Examples:
 *
 * USD:
 * 2900 -> 29
 *
 * JOD:
 * 2900 -> 29
 *
 * JPY:
 * 2900 -> 2900
 */
function convertStripeAmount(amount: number, currency: string): number {
  const normalizedCurrency = currency.toLowerCase();

  if (STRIPE_ZERO_DECIMAL_CURRENCIES.has(normalizedCurrency)) {
    return amount;
  }

  return amount / 100;
}

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
     *
     * Do NOT use getActiveSubscriptionByTenant().
     *
     * We still want billing history if the current subscription
     * is:
     *
     * - trialing
     * - active
     * - past_due
     * - pending
     * - payment_failed
     * - paused
     */

    const subscription =
      await subscriptionRepo.getCurrentSubscriptionByTenant(tenantId);

    if (!subscription || !subscription.paymentProviderSubscriptionId) {
      /*
       * No current subscription = no current-subscription
       * invoice history.
       */
      return {
        success: true,
        data: []
      };
    }

    /*
     * ========================================================
     * 2. FETCH RAW RECORDS
     * ========================================================
     *
     * Repository only returns database records.
     */

    const records =
      await invoiceRepo.getSuccessfulPaymentEventsBySubscriptionId(
        subscription.paymentProviderSubscriptionId
      );

    /*
     * ========================================================
     * 3. INTERPRET STRIPE EVENTS
     * ========================================================
     */

    const invoices: TenantInvoiceDto[] = [];

    /*
     * Defensively prevent the same Stripe invoice from
     * appearing more than once.
     */
    const seenInvoiceIds = new Set<string>();

    for (const record of records) {
      const event = record.payload as any;

      const invoice = event?.data?.object;

      if (!invoice?.id) {
        /*
         * Malformed / old audit record.
         */
        continue;
      }

      /*
       * =====================================================
       * IMPORTANT: IGNORE ZERO-VALUE INVOICES
       * =====================================================
       *
       * This implements the billing behavior we designed:
       *
       * Free trial:
       *
       * amount_paid = 0
       *      ↓
       * NOT shown as a real payment invoice
       *
       *
       * Actual charge:
       *
       * amount_paid > 0
       *      ↓
       * shown in billing history
       */

      const amountPaid = Number(invoice.amount_paid ?? 0);

      if (!Number.isFinite(amountPaid) || amountPaid <= 0) {
        continue;
      }

      /*
       * Prevent duplicates.
       */
      if (seenInvoiceIds.has(invoice.id)) {
        continue;
      }

      seenInvoiceIds.add(invoice.id);

      const currency =
        typeof invoice.currency === "string"
          ? invoice.currency.toLowerCase()
          : "";

      const billingReason =
        typeof invoice.billing_reason === "string"
          ? invoice.billing_reason
          : null;

      /*
       * Stripe Invoice periods can be represented at the
       * invoice level depending on API/version.
       */
      const periodStart = unixToIso(invoice.period_start);

      const periodEnd = unixToIso(invoice.period_end);

      invoices.push({
        /*
         * Stripe Invoice ID.
         *
         * Example:
         *
         * in_1ABC...
         */
        id: invoice.id,

        /*
         * Customer-facing invoice number when available.
         */
        invoiceNumber: invoice.number ?? null,

        /*
         * Invoice creation date.
         */
        date: unixToIso(invoice.created),

        /*
         * Frontend-friendly amount.
         */
        amount: convertStripeAmount(amountPaid, currency),

        /*
         * Always keep Stripe's original amount too.
         *
         * This is useful if the frontend later needs exact
         * accounting values without floating-point conversion.
         */
        amountMinor: amountPaid,

        currency,

        status: invoice.status ?? null,

        /*
         * initial
         * recurring
         * subscription_change
         * etc.
         */
        type: classifyInvoice(billingReason),

        billingReason,

        periodStart,

        periodEnd,

        /*
         * Stripe-hosted customer invoice documents.
         */
        pdfUrl: invoice.invoice_pdf ?? null,

        hostedUrl: invoice.hosted_invoice_url ?? null
      });
    }

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
