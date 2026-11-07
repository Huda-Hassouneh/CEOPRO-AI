// Existing tab IDs remain stable for bookmarks and owner guidance links.
export const ownerBillingGroups = [
  { id: 'plans', tabs: ['plans', 'plan-features', 'features'] },
  { id: 'custom-plans', tabs: ['custom-quotes', 'custom-plans', 'custom-pricing'] },
  { id: 'subscriptions', tabs: ['subscriptions'] },
  { id: 'economics', tabs: ['provider-accounting', 'pricing-studio'] },
  { id: 'promos', tabs: ['promos'] },
];

export function ownerBillingSelection(requested, available) {
  const allowed = new Set(available);
  const tab = allowed.has(requested) ? requested : 'plans';
  return { tab, group: ownerBillingGroups.find(group => group.tabs.includes(tab))?.id ?? 'plans' };
}
