import { Area, CartesianGrid, Line, ComposedChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';

export function DemandForecastChart({ points, detailed = false, t, formatDate, formatNumber }) {
  const chartPoints = points.map((point) => ({ ...point, rangeBase: point.lower, rangeSize: point.lower == null || point.upper == null ? null : point.upper - point.lower }));
  return <div className="demand-approved-chart" dir="ltr" role="img" aria-label={t('demandApproved.chart.label')}>
    <ResponsiveContainer width="100%" height="100%"><ComposedChart data={chartPoints} margin={{ top: 12, right: 14, left: 0, bottom: 0 }}>
      <CartesianGrid vertical={false} stroke="#ebeaf5" strokeDasharray="3 3" />
      <XAxis dataKey="date" tickFormatter={formatDate} minTickGap={32} axisLine={false} tickLine={false} tick={{ fontSize: 10, fill: '#7a7d8d' }} />
      <YAxis width={48} axisLine={false} tickLine={false} tick={{ fontSize: 10, fill: '#7a7d8d' }} />
      <Tooltip labelFormatter={formatDate} formatter={(value, name) => [formatNumber(value), t(`demandApproved.chart.${name}`)]} contentStyle={{ borderRadius: 10, borderColor: '#dfe3f1', fontSize: 11 }} />
      {detailed && <Area dataKey="rangeBase" stackId="confidence" stroke="none" fill="transparent" connectNulls={false} tooltipType="none" />}
      {detailed && <Area dataKey="rangeSize" stackId="confidence" stroke="none" fill="#cfc9fa" fillOpacity={.42} connectNulls={false} tooltipType="none" />}
      {detailed && <Line type="monotone" dataKey="actual" stroke="#72758a" strokeWidth={2} dot={false} connectNulls={false} />}
      {detailed && <Line type="monotone" dataKey="forecast" stroke="#2f2bce" strokeWidth={2.4} strokeDasharray="5 4" dot={false} connectNulls={false} />}
      {!detailed && <Line type="monotone" dataKey="value" stroke="#2f2bce" strokeWidth={2.5} dot={false} />}
    </ComposedChart></ResponsiveContainer>
  </div>;
}
