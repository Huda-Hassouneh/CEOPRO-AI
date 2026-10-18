// Stripe's payments API documents currencies as two-decimal unless they are
// explicitly listed as zero-decimal. This helper intentionally follows
// Stripe's API amount format rather than ISO 4217 decimal exponents.
const ZERO_DECIMAL_CURRENCIES = new Set([
  "BIF",
  "CLP",
  "DJF",
  "GNF",
  "JPY",
  "KMF",
  "KRW",
  "MGA",
  "PYG",
  "RWF",
  "UGX",
  "VND",
  "VUV",
  "XAF",
  "XOF",
  "XPF"
]);

export function getStripeCurrencyExponent(currency: string): 0 | 2 {
  const normalized = currency.trim().toUpperCase();
  return ZERO_DECIMAL_CURRENCIES.has(normalized) ? 0 : 2;
}

export function toStripeMinorUnits(amountMajor: number, currency: string): number {
  if (!Number.isFinite(amountMajor) || amountMajor < 0) {
    throw new Error("Currency amount must be a finite non-negative number");
  }

  return Math.round(amountMajor * 10 ** getStripeCurrencyExponent(currency));
}

export function fromStripeMinorUnits(amountMinor: number, currency: string): number {
  if (!Number.isFinite(amountMinor)) {
    throw new Error("Stripe amount must be a finite number");
  }

  return amountMinor / 10 ** getStripeCurrencyExponent(currency);
}
