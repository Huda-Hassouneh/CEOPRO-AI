import { CalendarDays, Minus, Package, TrendingDown, TrendingUp } from 'lucide-react';
import Card from '../../../shared/components/ui/Card.jsx';
import DataStatusBadge from '../../../shared/components/ui/DataStatusBadge.jsx';

const icons = { calendar: CalendarDays, package: Package, increase: TrendingUp, decrease: TrendingDown, stable: Minus };

export function DemandMetricCard({ metric, label, value }) {
  const Icon = icons[metric.icon] || Package;
  return <Card className="demand-approved-metric"><div className="demand-approved-metric__top"><span><Icon size={18} /></span><DataStatusBadge status={metric.dataStatus} /></div><div><small>{label}</small><strong>{value}</strong></div></Card>;
}
