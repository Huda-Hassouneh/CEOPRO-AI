import Card from '../../../shared/components/ui/Card.jsx';
import DataStatusBadge from '../../../shared/components/ui/DataStatusBadge.jsx';
import { DashboardIcon } from './DashboardIcon.jsx';

export function KpiCard({ metric, label }) {
  return <Card className={`dashboard-kpi-card is-${metric.tone || 'purple'}`}>
    <div className="dashboard-kpi-card__top">
      <div className="dashboard-kpi-card__icon"><DashboardIcon name={metric.icon} /></div>
      <DataStatusBadge status={metric.dataStatus} />
    </div>
    <div className="dashboard-kpi-card__body">
      <span className="dashboard-kpi-card__label">{label}</span>
      <strong>{metric.formattedValue}</strong>
    </div>
  </Card>;
}
