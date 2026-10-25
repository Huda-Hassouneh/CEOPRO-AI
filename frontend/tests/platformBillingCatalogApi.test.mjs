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

test('plan quota controls map numeric and module terms to the versioned Python endpoint', async () => {
  const calls = [];
  const api = createPlatformBillingCatalogApi({
    billing: {
      view: async () => ({ plans: [{ plan_key: 'growth', display_name: 'Growth',
        feature_limits: [{ feature_code: 'team_seats', unit: 'seats', limit_value: 5 }],
        entitlements: ['market_intelligence'] }] }),
      updatePlanFeature: async (planKey, body) => { calls.push([planKey, body]); return { catalog_versioned: true }; },
    },
  });
  const features = (await api.getPlanFeatures('growth')).data;
  assert.deepEqual(features.map((row) => row.feature_id), ['team_seats', 'market_intelligence']);
  await api.updatePlanFeatureLimit({ planId: 'growth', featureId: 'team_seats', limitValue: 12 });
  await api.unlinkFeatureFromPlan({ planId: 'growth', featureId: 'market_intelligence' });
  assert.deepEqual(calls, [
    ['growth', { feature_code: 'team_seats', included: true, limit_value: 12, reason: 'Owner changed a supported plan feature allowance.' }],
    ['growth', { feature_code: 'market_intelligence', included: false, limit_value: null, reason: 'Owner removed a supported feature from a plan.' }],
  ]);
});

test('original plan availability toggle maps to Python status; price and commercial edits remain guarded', async () => {
  const calls = [];
  const api = createPlatformBillingCatalogApi({ billing: {
    updatePlanStatus: async (planKey, body) => { calls.push([planKey, body]); return { is_active: body.active }; },
  } });
  const result = await api.updatePlan('growth', { isActive: false });
  assert.equal(result.is_active, false);
  assert.equal(calls[0][0], 'growth');
  assert.equal(calls[0][1].active, false);
  await assert.rejects(api.updatePlan('growth', { price: 60, currency: 'USD' }), /Stripe price versioning/);
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


test('original vendor-rate form maps to the versioned Python rate and draft binding contract', async () => {
  let captured;
  const api = createPlatformBillingCatalogApi({ billing: { saveVendorRate: async (body) => { captured = body; return { cost_rate: { cost_rate_id: 'r-1' }, binding: { binding_id: 'b-1' } }; } } });
  const result = await api.createVendorRate({ budgetKind: 'ai', vendor: 'provider-a', service: 'inference', billingUnit: 'input_token', unitCost: '0.00002', currency: 'USD', verificationStatus: 'confirmed', source: 'invoice reference INV-SYNTH-01', verifiedAt: '2026-10-20', effectiveFrom: '2026-10-25T00:00:00.000Z', featureId: 'rag_assistant', policyVersionId: 'policy-draft-1', usageBasis: 'limit_value', unitsPerFeatureUnit: '4', operationalMultiplier: '1.2', variabilityReserve: '1.1', metadata: {} });
  assert.equal(captured.budget_kind, 'ai');
  assert.equal(captured.unit_cost_usd, 0.00002);
  assert.equal(captured.feature_code, 'rag_assistant');
  assert.equal(captured.policy_version_id, 'policy-draft-1');
  assert.equal(captured.verification_evidence, 'invoice reference INV-SYNTH-01');
  assert.equal(result.binding.binding_id, 'b-1');
});

test('vendor-rate adapter refuses unsupported currency, unit, and unverified status before the API call', async () => {
  let calls = 0;
  const api = createPlatformBillingCatalogApi({ billing: { saveVendorRate: async () => { calls += 1; } } });
  const base = { budgetKind: 'data', vendor: 'provider-a', service: 'lookup', billingUnit: 'request', unitCost: 1, currency: 'USD', verificationStatus: 'confirmed', source: 'test source', verifiedAt: '2026-10-20', effectiveFrom: '2026-10-25T00:00:00.000Z', operationalMultiplier: 1, variabilityReserve: 1 };
  await assert.rejects(api.createVendorRate({ ...base, currency: 'EUR' }), /require USD/);
  await assert.rejects(api.createVendorRate({ ...base, billingUnit: 'credits' }), /Unsupported Python cost unit/);
  await assert.rejects(api.createVendorRate({ ...base, verificationStatus: 'estimated' }), /verified provider rate is required/);
  assert.equal(calls, 0);
});

test('owner quote composer uses Python draft, submit, and server pricing contracts', async () => {
  const calls = [];
  const api = createPlatformBillingCatalogApi({
    billing: {
      createQuote: async (body) => { calls.push(['create', body]); return { quote_id: 'q-synthetic', state: 'draft' }; },
      submitQuote: async (id, body) => { calls.push(['submit', id, body]); return { quote_id: id, state: 'submitted' }; },
      companies: async () => ({ items: [{ tenant_id: 't-synthetic', business_name: 'Synthetic tenant' }] }),
    },
    offers: { getConfigurator: async () => ({
      features: [{ featureCode: 'team_seats', unit: 'seats', aggregationType: 'max', resetCycle: 'lifetime' }],
      modules: [{ featureCode: 'competitor_management', selectionKind: 'included_feature' }],
    }) },
  });
  const tenants = (await api.getTenants()).data;
  assert.equal(tenants[0].id, 't-synthetic');
  const features = (await api.getFeatures()).data;
  assert.equal(features.find((item) => item.id === 'competitor_management').type, 'boolean');
  const result = await api.createCustomPlanQuote({
    tenantId: 't-synthetic', currency: 'JOD', targetGrossMarginPercent: 99,
    fxRate: 3.5, monthlyInfrastructureCost: 5000,
    features: [
      { featureId: 'competitor_management', limitValue: null, configuration: { monitoringFrequencyMinutes: 1440 } },
      { featureId: 'team_seats', limitValue: 8, estimatedUsage: 400 },
    ],
  });
  assert.equal(result.data.id, 'q-synthetic');
  assert.deepEqual(calls[0][1].feature_quantities, { team_seats: 8 });
  assert.deepEqual(calls[0][1].configuration, { enabledFeatures: ['competitor_management'], refreshFrequency: 'daily' });
  assert.deepEqual(calls[0][1].commercial_terms, {});
  assert.deepEqual(calls[0][1].economic_inputs, {});
  assert.deepEqual(calls[0][1].fx_evidence, {});
  assert.equal(calls[1][2].expected_revision, 1);
});

test('owner quote composer rejects unsupported cadence before creating a Python quote', async () => {
  let calls = 0;
  const api = createPlatformBillingCatalogApi({
    billing: { createQuote: async () => { calls += 1; } },
    offers: { getConfigurator: async () => ({ features: [], modules: [{ featureCode: 'competitor_management' }] }) },
  });
  await assert.rejects(api.createCustomPlanQuote({ tenantId: 't', features: [
    { featureId: 'competitor_management', configuration: { monitoringFrequencyMinutes: 30 } },
  ] }), /hourly, daily, or weekly/);
  assert.equal(calls, 0);
});


test('disabled promotions cannot be reactivated with silently ignored term edits', async () => {
  let activations = 0;
  const api = createPlatformBillingCatalogApi({
    billing: {
      promotions: async () => ({ items: [{ promotion_id: 'promo-1', status: 'disabled', code: 'SYNTHETIC',
        terms: { discount_type: 'percent', discount_value: '10', max_uses: 4, max_uses_per_tenant: 1,
          starts_at: null, expires_at: null }, plan_keys: ['starter'] }] }),
      activatePromotion: async () => { activations += 1; },
    },
  });
  await assert.rejects(api.updatePromoCode('promo-1', { isActive: true, discountValue: 20, approvalReference: 'TEST', approvalReason: 'fixture' }), /terms are immutable/);
  assert.equal(activations, 0);
});
