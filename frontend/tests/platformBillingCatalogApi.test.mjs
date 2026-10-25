import test from 'node:test';
import assert from 'node:assert/strict';
import { createPlatformBillingCatalogApi } from '../src/features/platform/platformBillingCatalogApi.js';

test('original billing presentation maps Python plan and feature contracts without changing plan authority', async () => {
  const api = createPlatformBillingCatalogApi({
    billing: { view: async (name) => name === 'plans' ? { plans: [{ plan_key: 'growth', display_name: 'Growth', monthly_price: '55.00', currency: 'USD', trial_days: 14, is_active: true, prices: [{ period_code: 'monthly', interval_months: 1 }], feature_limits: [{ feature_code: 'team_seats', unit: 'seats', limit_value: 5 }] }] } : {} },
    offers: { getConfigurator: async () => ({ features: [{ featureCode: 'team_seats', unit: 'seats', aggregationType: 'sum', resetCycle: 'billing_period' }] }) },
  });
  const plans = (await api.getPlans()).data;
  assert.equal(plans[0].id, 'growth');
  assert.equal(plans[0].name, 'Growth');
  assert.equal(plans[0].basePrice, '55.00');
  assert.equal((await api.getFeatures()).data[0].code, 'team_seats');
  assert.equal((await api.getPlanFeatures('growth')).data[0].limitValue, 5);
});

test('original quote list reflects Python tenant/revision data and never fabricates a quote price', async () => {
  const api = createPlatformBillingCatalogApi({
    billing: { quotes: async () => ({ quotes: [{ quoteId: 'q-1', tenantId: 't-1', businessName: 'Synthetic Co', state: 'submitted', updatedAt: '2026-10-25T00:00:00Z', currentRevision: { revisionNumber: 2, configuration: { enabledFeatures: ['market_intelligence'] }, featureQuantities: { team_seats: 4 }, commercialTerms: {} } }] }) },
  });
  const [quote] = (await api.getCustomPlanQuotes()).data;
  assert.equal(quote.id, 'q-1');
  assert.equal(quote.tenant.businessName, 'Synthetic Co');
  assert.equal(quote.revision, 2);
  assert.equal(quote.quantities.team_seats, 4);
  assert.equal(quote.finalPrice, undefined);
  assert.equal(quote.estimatedTotalCost, undefined);
});

test('unsupported Node-only catalog mutations fail explicitly instead of hitting a legacy endpoint', async () => {
  const api = createPlatformBillingCatalogApi({ billing: {} });
  await assert.rejects(api.getPromoCodes(), { code: 'BACKEND_CAPABILITY_UNAVAILABLE' });
  await assert.rejects(api.updatePlan('growth', {}), { code: 'BACKEND_CAPABILITY_UNAVAILABLE' });
  await assert.rejects(api.updateCustomPlanPricingPolicy({}), { code: 'BACKEND_CAPABILITY_UNAVAILABLE' });
});
