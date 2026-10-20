const TIERS = ['EXACT', 'EQUIVALENT', 'SIMILAR', 'ADDED_VALUE'];

// A spreadsheet must not run a scraped or typed name as a formula.
const csvCell = (value) => {
  const text = String(value ?? '');
  const safe = /^[=+\-@\t\r]/.test(text) ? `'${text}` : text;
  return `"${safe.replace(/"/g, '""')}"`;
};

// The price comparison report (GET /reports/price-comparison) as CSV, one row per product.
export function reportCsv(products) {
  const header = ['product', 'currency', 'your_price', 'best_tier', ...TIERS.map((tier) => `${tier.toLowerCase()}_count`), 'position_pct', 'range_low', 'range_high', 'band_pct', 'band_source'];
  const rows = products.map((p) => [
    p.name, p.currency, p.your_price, p.headline?.tier, ...TIERS.map((tier) => p.tiers[tier].count), p.headline?.position_pct,
    p.added_value_guidance?.range_low, p.added_value_guidance?.range_high, p.added_value_guidance?.band_pct, p.added_value_guidance?.band_source,
  ]);
  return [header, ...rows].map((row) => row.map(csvCell).join(',')).join('\n');
}
