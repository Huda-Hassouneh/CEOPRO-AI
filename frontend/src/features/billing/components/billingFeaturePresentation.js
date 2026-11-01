// Presentation metadata is supplied by the installed canonical JSON through API.
// Unknown codes stay visible; no category can affect technical identity/usage.
export function featureGroup(feature) {
  return feature?.category?.key || 'other';
}

export function categoryLabel(feature, locale, t) {
  return feature?.category?.[locale === 'ar' ? 'label_ar' : 'label_en'] || t('billing.catalog.guided.groups.other');
}

export function displayUnit(unit, t) {
  if (unit === 'KB') return t('common.units.kilobytes');
  const key = { products:'product',reports:'report',seats:'seat',credits:'credit',MB:'mb',
    sources:'source',images:'image',records:'review',tokens:'token',searches:'search',competitors:'competitor' }[unit];
  return key ? t(`billing.customPlan.unitNames.${key}`) : unit || '';
}

export function groupedFeatures(features) {
  const groups = new Map();
  for (const feature of [...features].sort((a, b) => (a.category?.display_order ?? 999) - (b.category?.display_order ?? 999) || (a.display_order ?? 999) - (b.display_order ?? 999))) {
    const key = featureGroup(feature);
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
  if (feature?.aggregationType === 'sum' || feature?.aggregation_type === 'sum') return 'consumable';
  if (unit.includes('minute') || unit.includes('hour') || unit.includes('day')) return 'cadence';
  return 'max';
}
