// Preview database projections and exact AI shapes; see dashboard-data-audit.md.
const uuid = (n) => `00000000-0000-4000-8000-${String(n).padStart(12, '0')}`;
export const previewContext = { tenantId: uuid(1), currency: 'JOD', asOf: '2026-09-14' };
export const products = [
  { product_id: uuid(10), tenant_id: uuid(1), product_name: { en: 'Home router', ar: 'راوتر منزلي' }, deleted_at: null },
  { product_id: uuid(11), tenant_id: uuid(1), product_name: { en: 'Wi-Fi extender', ar: 'مقوي إشارة واي فاي' }, deleted_at: null },
  { product_id: uuid(12), tenant_id: uuid(1), product_name: { en: 'Network adapter', ar: 'محول شبكة' }, deleted_at: null },
];
export const inventory = products.map((product, i) => ({ inventory_id: uuid(20 + i), tenant_id: uuid(1), product_id: product.product_id, stock_quantity: [42, 8, 19][i], reorder_level: 10 }));
export const competitors = ['Orange', 'Zain', 'Umniah'].map((competitor_name, i) => ({ global_competitor_id: uuid(30 + i), competitor_name }));
export const tenantCompetitors = competitors.map(({ global_competitor_id }) => ({ tenant_id: uuid(1), global_competitor_id, is_tracked: true }));
export const invoices = Array.from({ length: 180 }, (_, i) => ({
  invoice_id: uuid(100 + i), tenant_id: uuid(1), issue_date: new Date(Date.UTC(2026, 8, 14 - i)).toISOString(),
  total_amount: (12 + i % 9) * 25, currency: 'JOD', payment_status: 'PAID',
}));
export const invoiceItems = invoices.map((invoice, i) => ({ invoice_item_id: uuid(300 + i), tenant_id: uuid(1), invoice_id: invoice.invoice_id, product_id: products[i % 3].product_id, quantity: 12 + i % 9 }));
export const demandForecast = { forecast_id: uuid(500), product_id: uuid(10), expected_demand: 48, confidence_range_lower: 36, confidence_range_upper: 62, forecast_target_date: '2026-09-21', model_version: 'preview' };
export const businessSentiment = { status: 'OK', sentiment_score: 0.52, label_counts: { positive: 18, neutral: 5, negative: 3 }, sample_size: { status: 'low', minimum_required: 30 }, evidence_id: uuid(501) };
export const priceCompetitiveness = { value: 7.4, missing_factors: [] };
export const competitorScores = {
  [uuid(30)]: { value: 76, missing_factors: [] },
  [uuid(31)]: { value: 69, missing_factors: ['sentiment'] },
  [uuid(32)]: { value: null, missing_factors: ['price', 'sentiment', 'activity'] },
};
// Production must enforce tenant isolation server-side. No aggregate endpoint is assumed.
export function aggregateDashboard({ invoices: rows, invoiceItems: items, products: catalog, inventory: stock, tenantCompetitors: tracked }, { tenantId, currency, asOf }, days) {
  const end = Date.parse(`${asOf}T00:00:00Z`) + 86400000;
  const start = end - days * 86400000;
  const eligible = rows.filter((r) => r.tenant_id === tenantId && r.currency === currency && r.payment_status !== 'CANCELLED');
  const current = eligible.filter((r) => Date.parse(r.issue_date) >= start && Date.parse(r.issue_date) < end);
  const previous = eligible.filter((r) => Date.parse(r.issue_date) >= start - days * 86400000 && Date.parse(r.issue_date) < start);
  const sum = (list) => list.reduce((total, r) => total + Number(r.total_amount), 0);
  const revenue = sum(current), previousRevenue = sum(previous);
  const ids = new Set(current.map((r) => r.invoice_id));
  const active = catalog.filter((p) => p.tenant_id === tenantId && !p.deleted_at);
  const activeIds = new Set(active.map((p) => p.product_id));
  const available = stock.filter((r) => r.tenant_id === tenantId && activeIds.has(r.product_id));
  const lowStock = available.filter((r) => r.stock_quantity <= r.reorder_level);
  const buckets = Array.from({ length: Math.min(days, 7) }, (_, i) => {
    const from = start + Math.floor(i * days / Math.min(days, 7)) * 86400000;
    const to = start + Math.floor((i + 1) * days / Math.min(days, 7)) * 86400000;
    return { date: new Date(from).toISOString().slice(0, 10), revenue: sum(current.filter((r) => Date.parse(r.issue_date) >= from && Date.parse(r.issue_date) < to)) };
  });
  return { revenue, sales: items.filter((r) => r.tenant_id === tenantId && ids.has(r.invoice_id)).reduce((total, r) => total + r.quantity, 0), growth: previousRevenue === 0 ? null : (revenue - previousRevenue) / previousRevenue * 100,
    totalProducts: active.length, trackedCompetitors: tracked.filter((r) => r.tenant_id === tenantId && r.is_tracked).length,
    lowStock, inventoryCount: available.length, buckets };
}
export const previewDatabase = { invoices, invoiceItems, products, inventory, tenantCompetitors };
