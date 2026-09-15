import { ChevronDown } from 'lucide-react';
import DataStatusBadge from '../../../shared/components/ui/DataStatusBadge.jsx';

export function DashboardChartCard({ title, subtitle, children, selector, dataStatus, className = '' }) {
  return <section className={`dashboard-panel dashboard-chart-card ${className}`}><div className="dashboard-panel__header"><div><h2>{title}</h2>{subtitle && <p>{subtitle}</p>}</div><div className="dashboard-panel__meta">{dataStatus && <DataStatusBadge status={dataStatus} />}{selector && <button type="button" className="dashboard-select-preview">{selector}<ChevronDown size={14} /></button>}</div></div>{children}</section>;
}

export function DemandBarChart({ values, labels, ariaLabel }) {
  const max = Math.max(...values, 1);
  return <div className="dashboard-bar-chart" role="img" aria-label={ariaLabel}>{values.map((value, index) => <div className="dashboard-bar-chart__column" key={labels[index]}><span style={{ height: `${(value / max) * 100}%` }} /><small>{labels[index]}</small></div>)}</div>;
}

export function ForecastLineChart({ actual, projected, ariaLabel }) {
  const values = [...actual, ...projected]; const max = Math.max(...values); const min = Math.min(...values); const range = max - min || 1;
  const toPoints = (series, offset = 0) => series.map((value, index) => `${((index + offset) / (values.length - 1)) * 100},${78 - ((value - min) / range) * 62}`).join(' ');
  return <div className="dashboard-forecast-chart" role="img" aria-label={ariaLabel}><svg viewBox="0 0 100 84" preserveAspectRatio="none"><polyline points={toPoints(actual)} className="actual" /><polyline points={toPoints(projected, actual.length - 1)} className="projected" /></svg><div className="dashboard-chart-axis"><span>Mon</span><span>Tue</span><span>Wed</span><span>Thu</span><span>Fri</span><span>Sat</span><span>Sun</span></div></div>;
}
