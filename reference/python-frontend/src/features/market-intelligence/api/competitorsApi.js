import httpClient from '../../../shared/lib/httpClient.js';

// A small, fixed palette for the list table's avatar circle - purely a
// display accent (no real "brand color" is tracked server-side), picked
// deterministically from the competitor's name so the same competitor
// always gets the same color across re-renders/refetches.
const AVATAR_PALETTE = ['#f97316', '#111827', '#84cc16', '#dc2626', '#0ea5a8', '#1d4ed8', '#06b6d4', '#4f46e5', '#0f766e', '#6366f1'];

export function colorForName(name) {
  let hash = 0;
  for (let i = 0; i < name.length; i += 1) hash = (hash * 31 + name.charCodeAt(i)) >>> 0;
  return AVATAR_PALETTE[hash % AVATAR_PALETTE.length];
}

// Reshapes one GET /competitors row (backend/src/ai/routers/competitors.py,
// same real fields dashboard/competitors.py::get_competitor_directory()
// computes) into the 10-field tuple CompetitorTable.jsx already renders.
// Every field here is either a real backend value or an honest "unknown"
// placeholder ('—') - never a fabricated status/score for a signal
// the backend itself doesn't have yet (matches this codebase's existing
// honesty discipline, e.g. dashboard/competitors.py's own None handling).
// summary_line / strengths / weaknesses arrive as English sentences; these
// render the same facts in the interface language from the language-neutral
// fields sent alongside them (falling back to the English text for any
// code this build doesn't know yet).
export function competitorSummary(t, competitor) {
  if (competitor.tier === 'STRATEGIC' && competitor.product_overlap_pct != null) {
    return t('market.competitorsPage.summaryStrategic', { pct: Math.round(competitor.product_overlap_pct) });
  }
  if (competitor.tier !== 'STRATEGIC' && competitor.matched_product_count != null) {
    return t('market.competitorsPage.summaryRelevant', { count: competitor.matched_product_count });
  }
  return competitor.summary_line ?? '';
}

export function competitorTraits(t, codes, texts) {
  if (!codes) return texts || [];
  return codes.map((code, index) => {
    const key = `market.traits.${code}`;
    const text = t(key);
    return text === key ? (texts || [])[index] ?? code : text;
  });
}

function toTableRow(competitor) {
  const domain = competitor.website_url ? competitor.website_url.replace(/^https?:\/\//, '').replace(/\/$/, '') : '';
  const sentimentLabel = competitor.market_sentiment_label; // 'Positive' | 'Neutral' | 'Negative' | null
  const activityLabel = competitor.market_activity; // 'High' | 'Medium' | 'Low'
  return [
    competitor.name,
    domain,
    competitor.tier === 'STRATEGIC' ? 'market.competitorsPage.tierStrategic' : 'market.competitorsPage.tierRelevant',
    sentimentLabel ? `market.status.${sentimentLabel.toLowerCase()}` : '—',
    competitor.price_competitiveness != null ? `${competitor.price_competitiveness.toFixed(1)}/10` : '—',
    activityLabel ? `market.status.${activityLabel.toLowerCase()}` : '—',
    (t) => competitorSummary(t, competitor),
    competitor.last_updated || null, // ISO; formatted in the interface locale by CompetitorTable
    sentimentLabel ? sentimentLabel.toLowerCase() : 'neutral',
    colorForName(competitor.name),
    // The real global_competitor_id - GET /competitors/{id} (competitor
    // detail page) needs this exact value, never a slugified name (two
    // competitors can share a display name; a slug also isn't what the
    // backend's real id looks like at all).
    competitor.id,
  ];
}

export const competitorsApi = {
  // GET /competitors/landscape: market-wide and product-level competitors and
  // competitor coverage for every product.
  landscape: async () => (await httpClient.get('/competitors/landscape')).data,

  // The real backend endpoint - backend/src/ai/routers/competitors.py's
  // GET /competitors, which flattens dashboard/competitors.py's tier-
  // grouped directory into a single list. Returns both the raw
  // competitor objects (for anything that wants real fields directly)
  // and pre-shaped `rows` (CompetitorTable.jsx's existing tuple format),
  // so this is the one place that translates the backend contract into
  // the table's display contract.
  list: async () => {
    const response = await httpClient.get('/competitors');
    const competitors = response.data?.competitors ?? [];
    return { competitors, rows: competitors.map(toTableRow) };
  },

  // The real backend endpoint - backend/src/ai/routers/competitors.py's
  // GET /competitors/{id}, which returns the exact same real fields as
  // this same module's list() row for this one competitor (relevance
  // score, price competitiveness, sentiment/activity, strengths/
  // weaknesses, and either overlap_pct (STRATEGIC) or price_comparisons
  // (RELEVANT) - see that function's own docstring). 404s (competitor
  // not found, or not tracked by this tenant) surface as competitor: null
  // rather than throwing, so the page's own EmptyState renders.
  profile: async (id) => {
    try {
      const response = await httpClient.get(`/competitors/${encodeURIComponent(id)}`);
      return { id, competitor: response.data };
    } catch (error) {
      if (error?.response?.status === 404) return { id, competitor: null };
      throw error;
    }
  },

  // POST /competitors: the competitor, how it competes (MARKET = the whole
  // business, PRODUCT = specific products) and the products it competes on.
  create: async ({ name, website, competitionLevel, productIds = [] } = {}) => {
    const response = await httpClient.post('/competitors', {
      name, website_url: website, competition_level: competitionLevel || undefined, product_ids: productIds,
    });
    return { ok: true, competitor: response.data };
  },
};
