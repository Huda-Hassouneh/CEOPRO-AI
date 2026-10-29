// `compact` drops the cents from whole amounts ($55 rather than $55.00), for headline prices.
export function formatMoney(amount, currency, locale, { compact = false } = {}) {
  if (amount == null) return '';
  const whole = compact && Number.isInteger(amount);
  return new Intl.NumberFormat(locale, { style: 'currency', currency: currency || 'USD', minimumFractionDigits: whole ? 0 : undefined, maximumFractionDigits: whole ? 0 : 2 }).format(amount);
}
