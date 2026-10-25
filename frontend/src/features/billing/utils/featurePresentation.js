// Keep configured owner labels. Translate canonical code-derived fallbacks only.
export function featureDisplayName(code, feature = {}, locale = 'en', t = (key) => key) {
  if (locale === 'ar' && feature.name_ar) return feature.name_ar;
  const canonical = code.replaceAll('_', ' ');
  const configured = feature.name;
  if (locale !== 'ar' && configured && configured.toLowerCase() !== canonical.toLowerCase()) return configured;
  for (const key of [`billing.customPlan.featureNames.${code}`, `billing.modules.${code}`, `billing.management.usageLabels.${code}`]) {
    const value = t(key);
    if (value !== key) return value;
  }
  return configured || canonical;
}
