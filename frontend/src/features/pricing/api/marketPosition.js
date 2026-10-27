// Where a product's price stands, from one entry of GET /pricing/comparisons: against competitors' matching items
// (the ladder headline) when there are any, otherwise against the market estimate the price recommendation uses
// (backend/src/ai/pricing/estimation.py), and "none" only when nothing outside the company's own cost exists yet.
export const ESTIMATE_BASES = ['COMPARABLE_ESTIMATE', 'MARKET_REFERENCE', 'REGIONAL_ESTIMATE', 'PEER_ESTIMATE'];

export function marketPosition(summary) {
  const headline = summary?.headline;
  if (headline) return { kind: 'competitors', tier: headline.tier, pct: headline.position_pct, count: headline.count, headline };
  const estimate = summary?.estimate;
  if (estimate?.market_price != null && ESTIMATE_BASES.includes(estimate.basis)) {
    return { kind: 'estimate', basis: estimate.basis, pct: estimate.position_pct, marketPrice: estimate.market_price, count: estimate.count };
  }
  return { kind: 'none' };
}

// The coverage strip's bucket for one product: a comparison tier, "estimate", or "none".
export function coverageBucket(summary) {
  const position = marketPosition(summary);
  return position.kind === 'competitors' ? position.tier : position.kind;
}
