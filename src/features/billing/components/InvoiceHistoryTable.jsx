import { InvoiceDownloadButton } from "./InvoiceDownloadButton.jsx";

export function InvoiceHistoryTable({ invoices = [], locale, t }) {
  const date = new Intl.DateTimeFormat(locale, {
    dateStyle: "medium"
  });

  if (!invoices.length) {
    return (
      <p className="billing-usage-unavailable">{t("billing.invoices.empty")}</p>
    );
  }

  return (
    <div className="billing-invoice-wrap">
      <table className="billing-invoice-table">
        <thead>
          <tr>
            <th>{t("billing.invoices.columns.number")}</th>
            <th>{t("billing.invoices.columns.date")}</th>
            <th>{t("billing.invoices.columns.type")}</th>
            <th>{t("billing.invoices.columns.amount")}</th>
            <th>{t("billing.invoices.columns.status")}</th>
            <th>{t("billing.invoices.columns.document")}</th>
          </tr>
        </thead>

        <tbody>
          {invoices.map((invoice, index) => {
            const currency = String(invoice.currency || "USD").toUpperCase();

            const amount = new Intl.NumberFormat(locale, {
              style: "currency",
              currency
            }).format(Number(invoice.amount || 0));

            const createdAt = invoice.date ? new Date(invoice.date) : null;

            /*
             * Payment result returned by backend:
             *
             * paid
             * failed
             *
             * Keep invoice.status as fallback temporarily
             * for backwards compatibility.
             */
            const paymentStatus =
              invoice.paymentStatus ?? invoice.status ?? null;

            /*
             * Important if the backend returns multiple
             * payment attempts for the same Stripe invoice.
             */
            const rowKey =
              invoice.eventId ?? `${invoice.id}-${paymentStatus}-${index}`;

            return (
              <tr key={rowKey}>
                <td>{invoice.invoiceNumber || invoice.id}</td>

                <td>
                  {createdAt && !Number.isNaN(createdAt.getTime())
                    ? date.format(createdAt)
                    : "—"}
                </td>

                <td>
                  {t(`billing.invoices.types.${invoice.type || "other"}`)}
                </td>

                <td>{amount}</td>

                <td>
                  {paymentStatus === "paid"
                    ? "Paid"
                    : paymentStatus === "failed"
                      ? "Failed"
                      : "—"}
                </td>

                <td>
                  <InvoiceDownloadButton invoice={invoice} />
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
