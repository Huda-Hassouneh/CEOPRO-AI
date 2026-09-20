import { invoiceRepo } from "../repo/invoice.repo.js";
import subscriptionRepo from "../repo/subscription.repo.js";

export async function getTenantInvoicesService(tenantId: string) {
  try {
    // 1. Find the tenant's active subscription to get the Stripe Subscription ID
    const subscription =
      await subscriptionRepo.getActiveSubscriptionByTenant(tenantId);
    console.log(subscription?.paymentProviderSubscriptionId);

    if (!subscription || !subscription.paymentProviderSubscriptionId) {
      // If they have no subscription, they have no invoices. Return empty array safely.
      return { success: true, data: [] };
    }

    // 2. Fetch the raw audit events from the DB
    const auditRecords = await invoiceRepo.getPaidInvoicesBySubscriptionId(
      subscription.paymentProviderSubscriptionId
    );
    console.log(auditRecords);

    // 3. Map the raw Stripe JSON into a lightweight, frontend-friendly format
    const formattedInvoices = auditRecords.map((record) => {
      // The payload is the full Stripe Event object.
      const event = record.payload as any;

      // Extract the actual invoice object from inside the event data
      const invoice = event.data?.object || {};

      return {
        id: invoice.id,
        // Stripe uses unix timestamps (seconds), convert to JS Date (milliseconds)
        date: invoice.created
          ? new Date(invoice.created * 1000).toISOString()
          : null,

        // Convert cents to standard currency format
        amount: invoice.amount_paid ? invoice.amount_paid / 100 : 0,
        currency: invoice.currency,

        status: invoice.status,

        // The crucial URLs for the frontend
        pdfUrl: invoice.invoice_pdf || null,
        hostedUrl: invoice.hosted_invoice_url || null
      };
    });

    return { success: true, data: formattedInvoices };
  } catch (error: any) {
    console.error("[Get Invoices Error]:", error);
    return {
      success: false,
      code: "INTERNAL_SERVER_ERROR",
      message: "Failed to retrieve billing history."
    };
  }
}
