import { useId, useMemo } from 'react';
import { Area, CartesianGrid, ComposedChart, Line, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';

// Actual daily units (history) followed by the forecast path (next 30 days).
// Colours come from chartTheme.js (validated per theme); the forecast is
// also dashed, so the two never rely on colour alone. One y-axis (units).
import { CHART_ANIMATION, CHART_THEMES, useChartTheme } from './chartTheme.js';

export const SERIES_COLORS = { actual: CHART_THEMES.light.actual, forecast: CHART_THEMES.light.forecast };

export default function ForecastChart({ points = [], locale = 'en', labels, height = 300, todayDate }) {
  const dayFormat = useMemo(() => new Intl.DateTimeFormat(locale, { month: 'short', day: 'numeric', timeZone: 'UTC' }), [locale]);
  const numberFormat = useMemo(() => new Intl.NumberFormat(locale, { maximumFractionDigits: 1 }), [locale]);
  const data = useMemo(() => points.map((point) => ({ ...point, t: point.date })), [points]);
  const formatDay = (value) => dayFormat.format(new Date(`${value}T00:00:00Z`));
  const rtl = locale === 'ar';
  const c = useChartTheme();
  const uid = useId().replace(/:/g, '');

  return (
    <div className="apex-chart" dir="ltr">
      <div className="apex-chart__legend" dir={rtl ? 'rtl' : 'ltr'}>
        <span><i className="apex-chart__swatch" style={{ background: c.actual }} />{labels.actual}</span>
        <span><i className="apex-chart__swatch is-dashed" style={{ borderColor: c.forecast }} />{labels.forecast}</span>
      </div>
      <ResponsiveContainer width="100%" height={height}>
        <ComposedChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
          <defs>
            <linearGradient id={`apex-actual-fill-${uid}`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={c.actual} stopOpacity={0.35} />
              <stop offset="100%" stopColor={c.actual} stopOpacity={0} />
            </linearGradient>
            <linearGradient id={`apex-forecast-fill-${uid}`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={c.forecast} stopOpacity={0.28} />
              <stop offset="100%" stopColor={c.forecast} stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid vertical={false} strokeDasharray="0" />
          <XAxis dataKey="t" tickFormatter={formatDay} minTickGap={28} tickLine={false} axisLine={false} reversed={rtl} tick={{ fontSize: 11 }} />
          <YAxis tickFormatter={(value) => numberFormat.format(value)} width={44} tickLine={false} axisLine={false} orientation={rtl ? 'right' : 'left'} tick={{ fontSize: 11 }} />
          <Tooltip
            cursor={{ stroke: c.cursor, strokeWidth: 1 }}
            labelFormatter={formatDay}
            labelStyle={{ color: c.label, fontWeight: 600 }}
            itemStyle={{ color: c.item }}
            formatter={(value, key) => [numberFormat.format(value), key === 'actual' ? labels.actual : labels.forecast]}
          />
          {todayDate && <ReferenceLine x={todayDate} stroke={c.reference} strokeDasharray="3 4" label={{ value: labels.today, position: 'insideTopRight', fill: c.item, fontSize: 11 }} />}
          <Area type="monotone" dataKey="actual" stroke={c.actual} strokeWidth={2} fill={`url(#apex-actual-fill-${uid})`} dot={false} activeDot={{ r: 4, strokeWidth: 2, stroke: c.dotRing }} connectNulls={false} {...CHART_ANIMATION} />
          <Area type="monotone" dataKey="forecast" stroke={c.forecast} strokeWidth={2} strokeDasharray="6 4" fill={`url(#apex-forecast-fill-${uid})`} dot={false} activeDot={{ r: 4, strokeWidth: 2, stroke: c.dotRing }} connectNulls={false} {...CHART_ANIMATION} />
          <Line dataKey="none" hide />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}
