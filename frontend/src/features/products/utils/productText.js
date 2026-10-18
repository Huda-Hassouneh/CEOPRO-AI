export const productText = (value, locale) => typeof value === 'string' ? value : value?.[locale] || value?.en || value?.ar || value?.name || '—';
