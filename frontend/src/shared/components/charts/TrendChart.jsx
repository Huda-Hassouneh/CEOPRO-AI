import { useId, useMemo } from 'react';
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { CHART_ANIMATION, useChartTheme } from './chartTheme.js';

// One series over time (e.g. daily revenue). Single series: the panel title
// names it, so no legend. Same validated accent as ForecastChart's actuals.
export default function TrendChart({ points = [], locale = 'en', height = 260, formatValue, valueLabel }) {
  const dayFormat = useMemo(() => new Intl.DateTimeFormat(locale, { month: 'short', day: 'numeric', timeZone: 'UTC' }), [locale]);
  const compact = useMemo(() => new Intl.NumberFormat(locale, { notation: 'compact', maximumFractionDigits: 1 }), [locale]);
  const formatDay = (value) => dayFormat.format(new Date(`${value}T00:00:00Z`));
  const rtl = locale === 'ar';
  const c = useChartTheme();
  const uid = useId().replace(/:/g, '');
  return (
    <div className="apex-chart" dir="ltr">
      <ResponsiveContainer width="100%" height={height}>
        <AreaChart data={points} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
          <defs>
            <linearGradient id={`apex-trend-fill-${uid}`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={c.actual} stopOpacity={0.4} />
              <stop offset="100%" stopColor={c.actual} stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid vertical={false} />
          <XAxis dataKey="date" tickFormatter={formatDay} minTickGap={30} tickLine={false} axisLine={false} reversed={rtl} tick={{ fontSize: 11 }} />
          <YAxis tickFormatter={(v) => compact.format(v)} width={44} tickLine={false} axisLine={false} orientation={rtl ? 'right' : 'left'} tick={{ fontSize: 11 }} />
          <Tooltip cursor={{ stroke: c.cursor }} labelFormatter={formatDay} labelStyle={{ color: c.label, fontWeight: 600 }} itemStyle={{ color: c.item }} formatter={(value) => [formatValue ? formatValue(value) : value, valueLabel]} />
          <Area type="monotone" dataKey="value" stroke={c.actual} strokeWidth={2} fill={`url(#apex-trend-fill-${uid})`} dot={false} activeDot={{ r: 4, strokeWidth: 2, stroke: c.dotRing }} {...CHART_ANIMATION} />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
