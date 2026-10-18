import { sourceFreshness } from "../../market-intelligence/service/market-int.calculations.js";
export function monitoringMinutes(metadata: unknown): number | null {
  const config = (metadata as { configuration?: { monitoringFrequencyMinutes?: unknown } } | null)?.configuration;
  const value = config?.monitoringFrequencyMinutes;
  return typeof value === 'number' && Number.isInteger(value) && value > 0 && value <= 525600 ? value : null;
}
type Observation = { competitor_price_id: string; currency: string; scraped_price: unknown; observed_at: Date; is_available: boolean; source_status: string; is_exact_data: boolean };
export function observationReason(row: Observation | undefined, now: Date, maxAge: number | null): string | null {
  if (!row) return 'NO_PRICE';
  if (row.source_status !== 'ALLOWED') return 'SOURCE_BLOCKED';
  if (!row.is_available) return 'UNAVAILABLE';
  if (!row.is_exact_data) return 'ESTIMATED_PRICE';
  const price = Number(row.scraped_price);
  if (!Number.isFinite(price) || price <= 0) return 'INVALID_PRICE';
  const freshness = sourceFreshness(row.observed_at, now, maxAge);
  if (!freshness.timestamp) return 'INVALID_DATE';
  if (freshness.status === 'stale') return 'STALE_PRICE';
  return null;
}
export function priceComparison(prices: Observation[], currency: string, ourPrice: unknown, confirmed: boolean, now: Date, maxAge: number | null, sourceAllowed = true) {
  const ordered = [...prices].sort((a,b) => b.observed_at.getTime() - a.observed_at.getTime() || b.competitor_price_id.localeCompare(a.competitor_price_id));
  // Check the latest same-currency observation; never fall back behind a blocked or stale latest observation.
  const latest = ordered.find(row => row.currency === currency);
  const reason = !sourceAllowed ? 'SOURCE_BLOCKED' : !confirmed ? 'MATCH_UNCONFIRMED' : !latest && prices.length ? 'CURRENCY_MISMATCH' : observationReason(latest, now, maxAge);
  const ours = Number(ourPrice); const validOurs = Number.isFinite(ours) && ours >= 0;
  const actualReason = reason ?? (!validOurs ? 'INVALID_OUR_PRICE' : null);
  const price = actualReason ? null : Number(latest!.scraped_price);
  return { competitorPrice: price, reason: actualReason, lastUpdated: latest?.observed_at ?? null,
    priceDifference: price === null ? null : price - ours,
    priceDifferencePercent: price === null || ours === 0 ? null : (price - ours) / ours * 100 };
}
export function priceActivity(prices: Observation[], now: Date, maxAge: number | null) {
  const groups = new Map<string, Observation[]>();
  for (const row of prices) { const list = groups.get(row.currency) ?? []; list.push(row); groups.set(row.currency, list); }
  const activity = [];
  for (const rows of groups.values()) {
    rows.sort((a,b) => b.observed_at.getTime() - a.observed_at.getTime() || b.competitor_price_id.localeCompare(a.competitor_price_id));
    for (let i=0; i<rows.length-1; i++) {
      const current=rows[i]!, previous=rows[i+1]!;
      if (observationReason(current,now,maxAge) || observationReason(previous,now,maxAge) || current.observed_at <= previous.observed_at) continue;
      const oldPrice=Number(previous.scraped_price), newPrice=Number(current.scraped_price);
      if (oldPrice !== newPrice) activity.push({ id:current.competitor_price_id,previousPrice:oldPrice,newPrice,currency:current.currency,date:current.observed_at });
    }
  }
  return activity;
}
