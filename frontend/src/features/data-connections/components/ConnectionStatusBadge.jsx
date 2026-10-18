import {
  AlertTriangle,
  Check,
  CirclePause,
  CirclePlus,
  LoaderCircle,
  XCircle
} from "lucide-react";
import { normalizeConnectionStatus, connectionStatusLabel } from '../utils/connectionPresentation.js';

const icons = {
  connected: Check,
  synced: Check,
  configured: CirclePlus,
  paused: CirclePause,
  disconnected: XCircle,
  completed: Check,
  processing: LoaderCircle,
  needsAttention: AlertTriangle,
  failed: XCircle
};

export function ConnectionStatusBadge({ status = "", t }) {
  const statusKey = normalizeConnectionStatus(status);
  const Icon = icons[statusKey] || AlertTriangle;

  return (
    <span className={`connect-data-status is-${statusKey}`}>
      <Icon size={11} aria-hidden="true" />
      <span>{connectionStatusLabel(status, t)}</span>
    </span>
  );
}
