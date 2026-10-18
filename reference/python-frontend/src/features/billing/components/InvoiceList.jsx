import { ExternalLink } from 'lucide-react';
import Badge from '../../../shared/components/ui/Badge.jsx';
import { formatMoney } from '../utils/money.js';

export function InvoiceList({ invoices, locale, t, formatDate }) {
  if (!invoices?.length) return <p className="billing-usage-unavailable">{t('billing.invoices.empty')}</p>;
  return <div className="billing-comparison-wrap" tabIndex={0} role="region" aria-label={t('common.scrollableTable')}><table className="billing-comparison-table billing-invoice-table">
    <thead><tr><th>{t('billing.invoices.date')}</th><th>{t('billing.invoices.amount')}</th><th>{t('billing.invoices.status')}</th><th>{t('billing.invoices.document')}</th></tr></thead>
    <tbody>{invoices.map((invoice) => <tr key={invoice.invoice_id}>
      <td>{formatDate(invoice.paid_at || invoice.created_at)}</td>
      <td><bdi>{formatMoney(invoice.amount, invoice.currency, locale)}</bdi></td>
      <td><Badge variant={invoice.status === 'succeeded' ? 'light-success' : 'error'}>{t(`billing.invoices.${invoice.status}`)}</Badge></td>
      <td>{(invoice.invoice_pdf_url || invoice.hosted_invoice_url)
        ? <a href={invoice.invoice_pdf_url || invoice.hosted_invoice_url} target="_blank" rel="noreferrer">{t('billing.invoices.view')} <ExternalLink size={12} aria-hidden="true" /></a>
        : '—'}</td>
    </tr>)}</tbody>
  </table></div>;
}
