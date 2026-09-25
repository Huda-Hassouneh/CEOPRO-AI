// Fictional, deterministic development fixtures. No actual customer or billing data.
export function createPreviewData() {
  const names = ['Luma Trading', 'Cedar & Co.', 'Orbit Supply', 'Noura Goods', 'Juniper Retail', 'Atlas Pantry', 'Mosaic Home', 'Solstice Labs', 'Olive Lane', 'Dune Commerce', 'Willow Studio', 'Nova Distribution'];
  const people = ['Maya Noor', 'Sami Faris', 'Lina Ward', 'Omar Reed', 'Nadia Vale', 'Tariq Stone', 'Hana Bloom', 'Rami West', 'Sara Moon', 'Zaid Lake', 'Dana Finch', 'Adam Ray'];
  const companies = names.map((name, i) => ({ id: `company-${i + 1}`, name, industry: ['retail', 'wholesale', 'technology'][i % 3], country: ['JO', 'AE', 'SA'][i % 3], planId: ['standard', 'pro', 'custom'][i % 3], subscriptionStatus: i % 3 === 1 && i % 2 === 1 ? 'trial' : 'active', status: i === 8 ? 'suspended' : 'active', createdAt: `2026-${String(4 + Math.floor(i / 2)).padStart(2, '0')}-${String(3 + i).padStart(2, '0')}T09:00:00Z`, updatedAt: '2026-09-14T09:00:00Z', notes: '', users: 2, products: 12 + i * 3, competitors: 2 + i % 3, documents: 3 + i, usage: { products: 12 + i * 3, competitors: 2 + i % 3, ragQueries: 22 + i * 5, reports: 2 + i, storageGb: 0.5 + i / 10 } }));
  const users = companies.flatMap((c, i) => [0, 1].map(n => ({ id: `user-${i * 2 + n + 1}`, name: people[(i + n) % people.length], email: `member${i * 2 + n + 1}@example.test`, companyId: c.id, company: c.name, role: n ? 'staff' : 'owner', status: 'active', createdAt: c.createdAt })));
  const subscriptions = companies.map((c, i) => ({ id: `subscription-${i + 1}`, companyId: c.id, company: c.name, planId: c.planId, status: c.subscriptionStatus, billingPeriod: ['monthly', 'three-months', 'six-months'][i % 3], createdAt: c.subscriptionStatus === 'trial' ? '2026-09-14T09:00:00Z' : c.createdAt, trialEndsAt: c.subscriptionStatus === 'trial' ? '2026-09-28T09:00:00Z' : null, renewsAt: null }));
  return { companies, users, subscriptions, 'admin-team': [
    { id: 'preview-admin', name: 'Alex Rowan', email: 'alex@example.test', role: 'owner', status: 'active', createdAt: '2026-04-01T09:00:00Z' },
    { id: 'admin-2', name: 'Sam Ellis', email: 'sam@example.test', role: 'admin', status: 'active', createdAt: '2026-05-02T09:00:00Z' },
    { id: 'admin-3', name: 'Robin Sage', email: 'robin@example.test', role: 'admin', status: 'active', createdAt: '2026-06-03T09:00:00Z' },
    { id: 'admin-4', name: '', email: 'avery@example.test', role: 'admin', status: 'pending', createdAt: '2026-09-12T09:00:00Z' },
  ], 'audit-logs': [], settings: { name: 'CEO PRO', supportEmail: 'support@example.test', language: 'en', currency: 'USD' }, sessions: [{ id: 'preview-session', device: 'previewDevice', current: true, lastActive: '2026-09-15T09:00:00Z' }, { id: 'preview-other', device: 'previewDevice', current: false, lastActive: '2026-09-14T09:00:00Z' }] };
}

