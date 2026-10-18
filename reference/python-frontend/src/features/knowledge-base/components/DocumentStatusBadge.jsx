import { AlertCircle, CheckCircle2, LoaderCircle } from 'lucide-react';

const statusIcons = { ready: CheckCircle2, complete: CheckCircle2, processing: LoaderCircle, failed: AlertCircle };

export function DocumentStatusBadge({ status, t }) {
  if (!status) return null;
  const normalizedStatus = status === 'complete' ? 'ready' : status;
  const Icon = statusIcons[status] || AlertCircle;
  return <span className={`rag-document-status is-${normalizedStatus}`}>
    <Icon size={12} aria-hidden="true" />
    {t(`ragAssistant.documents.status.${normalizedStatus}`)}
  </span>;
}
