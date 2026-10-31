// Display-only grouping of the executable catalog. Unknown codes remain visible.
const GROUPS = {
  operations: ['dashboard_analytics', 'product_management', 'tracked_products', 'team_seats'],
  data: ['data_integration', 'connected_data_sources', 'document_extraction', 'document_storage_mb'],
  market: ['competitor_management', 'tracked_competitors', 'web_searches', 'market_intelligence', 'sentiment_analysis'],
  intelligence: ['rag_assistant', 'demand_prediction', 'marketing_image_generation', 'ai_credits', 'data_credits'],
  reporting: ['monthly_reports'],
};

export function featureGroup(code) {
  return Object.entries(GROUPS).find(([, codes]) => codes.includes(code))?.[0] || 'other';
}

export function groupedFeatures(features) {
  const groups = new Map();
  for (const feature of features) {
    const key = featureGroup(feature.code);
    groups.set(key, [...(groups.get(key) || []), feature]);
  }
  return [...groups];
}

export function featureUsageType(feature) {
  const code = feature?.code || feature?.id || '';
  const unit = String(feature?.unit || '').toLowerCase();
  if (feature?.type === 'boolean') return 'boolean';
  if (code === 'ai_credits' || code === 'data_credits') return 'credits';
  if (code === 'document_storage_mb' || unit === 'mb' || unit === 'gb') return 'storage';
  if (unit.includes('minute') || unit.includes('hour') || unit.includes('day')) return 'cadence';
  return 'max';
}
