import { BarChart3, Gauge, ScanSearch, Users } from 'lucide-react';
import Card from '../../../shared/components/ui/Card.jsx';
import DataStatusBadge from '../../../shared/components/ui/DataStatusBadge.jsx';

const icons = { users: Users, composite: BarChart3, segment: ScanSearch, price: Gauge };

export function MarketIntelligenceMetricCard({ metric, label, value }) {
  const Icon = icons[metric.icon] || BarChart3;
  return <Card className="market-main-metric">
    <div className="market-main-metric__top"><span className="market-main-metric__icon"><Icon size={18} aria-hidden="true" /></span><DataStatusBadge status={metric.dataStatus} /></div>
    <div className="market-main-metric__body"><span>{label}</span><strong>{value}</strong></div>
  </Card>;
}
