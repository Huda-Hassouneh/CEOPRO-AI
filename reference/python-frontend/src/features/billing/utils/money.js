export function formatMoney(amount, currency, locale) {
  if (amount == null) return '';
  return new Intl.NumberFormat(locale, { style: 'currency', currency: currency || 'USD', maximumFractionDigits: 2 }).format(amount);
}
