export function MarketTrendChart({ current, previous, labels, ariaLabel, className = '', currentLabel = 'This Year', previousLabel = 'Last Year' }) {
  const all = [...current, ...previous]; const min = Math.min(...all); const max = Math.max(...all); const range = max - min || 1;
  const points = (series) => series.map((value, index) => `${(index / (series.length - 1)) * 100},${92 - ((value - min) / range) * 72}`).join(' ');
  return <div className={`market-trend-chart ${className}`} role="img" aria-label={ariaLabel}><svg viewBox="0 0 100 100" preserveAspectRatio="none"><polyline className="market-trend-chart__previous" points={points(previous)} /><polyline className="market-trend-chart__current" points={points(current)} /></svg><div className="market-trend-chart__labels">{labels.map((label) => <span key={label}>{label}</span>)}</div><div className="market-chart-legend"><span className="current">{currentLabel}</span><span className="previous">{previousLabel}</span></div></div>;
}

export function SeasonalBarChart({ historical, current, labels, ariaLabel }) {
  const max = Math.max(...historical, ...current);
  return <div className="market-seasonal-chart" role="img" aria-label={ariaLabel}>{labels.map((label, index) => <div className="market-seasonal-chart__group" key={label}><div><i style={{ height: `${(historical[index] / max) * 100}%` }} /><b style={{ height: `${(current[index] / max) * 100}%` }} /></div><small>{label}</small></div>)}</div>;
}
