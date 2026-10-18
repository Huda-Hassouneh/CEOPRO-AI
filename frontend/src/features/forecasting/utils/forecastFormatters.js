export function asForecastDate(value) {
  if (value instanceof Date) return Number.isFinite(value.getTime()) ? value : null;
  if (typeof value !== 'string' || !value.trim()) return null;
  const dateOnly = /^\d{4}-\d{2}-\d{2}$/.test(value);
  if (!dateOnly && !/^\d{4}-\d{2}-\d{2}T/.test(value)) return null;
  const calendar = new Date(`${value.slice(0, 10)}T00:00:00Z`);
  if (!Number.isFinite(calendar.getTime()) || calendar.toISOString().slice(0, 10) !== value.slice(0, 10)) return null;
  const parsed = new Date(dateOnly ? `${value}T00:00:00Z` : value);
  if (!Number.isFinite(parsed.getTime()) || (dateOnly && parsed.toISOString().slice(0, 10) !== value)) return null;
  return parsed;
}
export function localize(value, locale) {
  if (typeof value === 'string') return value || '—';
  if (value && typeof value === 'object') return [value[locale], value.en, value.ar].find(v => typeof v === 'string' && v.trim()) || '—';
  return '—';
}
export function forecastFormatters(locale, unavailable = '—') {
  const number = new Intl.NumberFormat(locale, { maximumFractionDigits: 1 });
  const date = new Intl.DateTimeFormat(locale, { year: 'numeric', month: 'short', day: 'numeric', timeZone: 'UTC' });
  const formatNumber = value => value == null || typeof value === 'boolean' || (typeof value === 'string' && !value.trim()) || !Number.isFinite(Number(value)) ? unavailable : number.format(Number(value));
  const formatDate = value => { const parsed = asForecastDate(value); return parsed ? date.format(parsed) : unavailable; };
  const formatRange = value => value?.lower == null || value?.upper == null ? unavailable : `${formatNumber(value.lower)}–${formatNumber(value.upper)}`;
  const formatPeriod = row => row.endDate && row.endDate !== row.date ? `${formatDate(row.date)} – ${formatDate(row.endDate)}` : formatDate(row.date);
  const formatMetric = (metric, units) => {
    if (metric.format === 'range') return formatRange(metric.value);
    if (metric.format === 'date') return formatDate(metric.value);
    if (metric.value == null) return unavailable;
    return `${formatNumber(metric.value)}${metric.format === 'percent' ? '%' : metric.format === 'units' ? ` ${units}` : ''}`;
  };
  return { formatNumber, formatDate, formatRange, formatPeriod, formatMetric };
}
