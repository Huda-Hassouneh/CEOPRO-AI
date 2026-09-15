import { AlertTriangle, Check, LoaderCircle, XCircle } from 'lucide-react';

const icons = { connected: Check, completed: Check, processing: LoaderCircle, needsAttention: AlertTriangle, failed: XCircle };

export function ConnectionStatusBadge({ status, t }) {
  const Icon = icons[status] || AlertTriangle;
  return <span className={`connect-data-status is-${status}`}><Icon size={11} aria-hidden="true" /><span>{t(`connectData.statuses.${status}`)}</span></span>;
}
