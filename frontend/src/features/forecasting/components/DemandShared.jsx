import { Activity, BarChart3, CalendarDays, CircleDollarSign, Gift, Minus, Package, Smartphone, Target, TrendingDown, TrendingUp, Wifi } from 'lucide-react';
import Badge from '../../../shared/components/ui/Badge.jsx';
import Card from '../../../shared/components/ui/Card.jsx';

const icons = { activity: Activity, bars: BarChart3, calendar: CalendarDays, gift: Gift, mobile: Smartphone, money: CircleDollarSign, package: Package, stable: Minus, target: Target, trendDown: TrendingDown, trendUp: TrendingUp, wifi: Wifi };

export function DemandKpiCard({ item, t }) {
  const Icon = icons[item.icon] || Package;
  return <Card className={`demand-kpi${item.tone ? ` is-${item.tone}` : ''}`}>
    <span className="demand-kpi__icon"><Icon size={19}/></span>
    <div><small>{t(item.labelKey)}</small><strong><bdi>{item.value}</bdi>{item.detail && <em>{item.detail}</em>}</strong>{item.suffixKey && <span>{t(item.suffixKey)}</span>}{item.trend && <i>{item.trend}</i>}{item.detailKey && <p>{t(item.detailKey)}</p>}</div>
    {item.progress && <span className="demand-kpi__ring" style={{'--progress': `${item.progress * 3.6}deg`}}><b>{item.progress}%</b></span>}
    {item.series && <MiniSparkline values={item.series}/>} 
  </Card>;
}

export function MiniSparkline({ values, negative = false }) {
  const max = Math.max(...values); const min = Math.min(...values); const range = max - min || 1;
  const points = values.map((value,index)=>`${(index/(values.length-1))*100},${28-((value-min)/range)*24}`).join(' ');
  return <svg className={`demand-sparkline${negative?' is-negative':''}`} viewBox="0 0 100 32" preserveAspectRatio="none" aria-hidden="true"><polyline points={points}/></svg>;
}

const linePoints = (values, min, range, start = 0) => values.map((value,index)=>`${((start+index)/11)*100},${88-((value-min)/range)*76}`).join(' ');

export function DemandLineChart({ labels, historical, predicted, previous, lower, upper, t, detailed = false }) {
  const values = [...(historical||[]), ...(predicted||[]), ...(previous||[]), ...(lower||[]), ...(upper||[])];
  const min = Math.min(...values) * .9; const range = Math.max(...values) - min || 1;
  const historicalPoints = linePoints(historical || [], min, range);
  const predictedPoints = predicted ? linePoints(predicted, min, range, Math.max(0,(historical?.length||1)-1)) : '';
  const previousPoints = previous ? linePoints(previous, min, range) : '';
  const band = lower && upper ? `${linePoints(upper,min,range,5)} ${linePoints([...lower].reverse(),min,range,5).split(' ').reverse().join(' ')}` : '';
  return <div className={`demand-line-chart${detailed?' is-detailed':''}`} role="img" aria-label={t('demand.charts.demandLabel')}>
    <svg viewBox="0 0 100 100" preserveAspectRatio="none">
      {band && <polygon className="demand-line-chart__band" points={band}/>} 
      {previousPoints && <polyline className="is-previous" points={previousPoints}/>} 
      <polyline className="is-historical" points={historicalPoints}/>
      {predictedPoints && <polyline className="is-predicted" points={predictedPoints}/>} 
      {detailed && <line className="demand-today" x1="45.45" x2="45.45" y1="5" y2="92"/>}
    </svg>
    {detailed && <span className="demand-today-label">{t('demand.charts.today')}</span>}
    <div className="demand-chart-labels">{labels.map((label)=><span key={label}>{t(label)}</span>)}</div>
    <div className="demand-chart-legend"><span className="historical">{t(predicted?'demand.charts.historical':'demand.charts.thisYear')}</span>{predicted && <span className="predicted">{t('demand.charts.predicted')}</span>}{previous && <span className="previous">{t('demand.charts.previous')}</span>}{band && <span className="confidence">{t('demand.charts.confidence')}</span>}</div>
  </div>;
}

export function ProductIdentity({ product, t, compact = false }) {
  return <div className={`demand-product${compact?' is-compact':''}`}><span className={`demand-product__thumb tone-${product.tone}`}><Package size={compact?16:24}/></span><div><strong>{product.name}</strong><small>{compact?t(product.categoryKey):`${t('demand.common.sku')}: ${product.sku}`}</small></div></div>;
}

export function AccuracyRing({ value }) {
  return <span className="demand-accuracy" style={{'--accuracy':`${value*3.6}deg`}}><b>{value}%</b></span>;
}

export function TrendBadge({ tone, t }) {
  const increasing = tone === 'increasing';
  return <Badge variant={increasing?'light-success':'error'} className="demand-status">{increasing?'↑':'↓'} {t(`demand.status.${tone}`)}</Badge>;
}
