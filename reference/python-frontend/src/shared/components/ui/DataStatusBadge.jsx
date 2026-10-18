import { Calculator, Check, Clock3 } from 'lucide-react';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import Tooltip from './Tooltip.jsx';

export const DATA_STATUSES = Object.freeze({
  VERIFIED: 'verified',
  DERIVED: 'derived',
  ESTIMATED: 'estimated',
});

const statusIcons = {
  [DATA_STATUSES.VERIFIED]: Check,
  [DATA_STATUSES.DERIVED]: Calculator,
  [DATA_STATUSES.ESTIMATED]: Clock3,
};

export default function DataStatusBadge({ status, className = '' }) {
  const { t } = useI18n();
  const normalizedStatus = Object.values(DATA_STATUSES).includes(status) ? status : null;
  if (!normalizedStatus) return null;
  const Icon = statusIcons[normalizedStatus];
  const label = t(`dataStatus.${normalizedStatus}.label`);

  return (
    <Tooltip content={t(`dataStatus.${normalizedStatus}.description`)}>
      <span className={`data-status-badge is-${normalizedStatus} ${className}`.trim()} aria-label={label}>
        <Icon size={11} strokeWidth={2.4} aria-hidden="true" />
        <span>{label}</span>
      </span>
    </Tooltip>
  );
}
