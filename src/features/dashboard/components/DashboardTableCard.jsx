import { ArrowUpRight } from 'lucide-react';
import DataStatusBadge from '../../../shared/components/ui/DataStatusBadge.jsx';

export function DashboardTableCard({ title, subtitle, dataStatus, actionLabel, onAction, children, className = '' }) {
  return (
    <section className={`dashboard-panel dashboard-table-card ${className}`.trim()}>
      <div className="dashboard-panel__header">
        <div>
          <h2>{title}</h2>
          {subtitle && <p>{subtitle}</p>}
        </div>
        {dataStatus && <DataStatusBadge status={dataStatus} />}
      </div>
      {children}
      {actionLabel && <button type="button" className="dashboard-link dashboard-card-action" onClick={onAction}>{actionLabel}<ArrowUpRight size={14} aria-hidden="true" /></button>}
    </section>
  );
}
