export function MiniSparkline({ values = [], tone = 'purple', label = 'Trend' }) {
  if (!values.length) return null;
  const max = Math.max(...values); const min = Math.min(...values); const range = max - min || 1;
  const points = values.map((value, index) => `${(index / (values.length - 1 || 1)) * 100},${34 - ((value - min) / range) * 27}`).join(' ');
  return <svg className={`dashboard-sparkline is-${tone}`} viewBox="0 0 100 38" role="img" aria-label={label}><polyline points={points} fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" /></svg>;
}
