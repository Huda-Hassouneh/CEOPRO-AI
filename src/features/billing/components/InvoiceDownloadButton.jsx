import { Download, ExternalLink } from 'lucide-react';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';

export function InvoiceDownloadButton({ invoice }) {
  const { t } = useI18n();
  const url = invoice?.pdfUrl || invoice?.hostedUrl;
  if (!url) return <span className="billing-invoice-unavailable">{t('billing.invoices.unavailable')}</span>;

  return (
    <a
      className="billing-invoice-link"
      href={url}
      target="_blank"
      rel="noopener noreferrer"
    >
      {invoice.pdfUrl ? <Download size={13} /> : <ExternalLink size={13} />}
      {invoice.pdfUrl ? t('billing.invoices.download') : t('billing.invoices.open')}
    </a>
  );
}
