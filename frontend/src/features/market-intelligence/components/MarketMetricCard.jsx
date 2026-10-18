import { BarChart3, CircleDollarSign, Gauge, Sparkles, TrendingUp, Users } from 'lucide-react';
import Card from '../../../shared/components/ui/Card.jsx';

const iconMap = { competitors: Users, sentiment: Sparkles, price: Gauge, growth: TrendingUp, money: CircleDollarSign, activity: BarChart3 };
export function MarketMetricCard({ item, t }) {
  const Icon = iconMap[item.icon] || BarChart3;
  return <Card className={`market-metric-card is-${item.tone}`}><span className="market-metric-card__icon"><Icon size={18} /></span><span className="market-metric-card__body"><small>{t(item.labelKey)}</small><strong>{item.value || t(item.valueKey)}</strong><span>{item.trend} <em>{t(item.trendKey)}</em></span>{item.progress !== undefined && <i className="market-progress"><b style={{ width: `${item.progress}%` }} /></i>}</span></Card>;
}
