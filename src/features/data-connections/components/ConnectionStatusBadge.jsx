import { AlertTriangle, Check, LoaderCircle, XCircle } from "lucide-react";

const icons = {
  connected: Check,
  completed: Check,
  processing: LoaderCircle,
  needsAttention: AlertTriangle,
  failed: XCircle
};

export function ConnectionStatusBadge({ status = "", t }) {
  const lowredStatus = status.toLowerCase();
  const Icon = icons[lowredStatus] || AlertTriangle;
  return (
    <span className={`connect-data-status is-${lowredStatus}`}>
      <Icon size={11} aria-hidden="true" />
      <span>{t(`connectData.statuses.${lowredStatus}`)}</span>
    </span>
  );
}
