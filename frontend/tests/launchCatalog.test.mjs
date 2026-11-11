import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { mapPlan } from '../src/features/billing/api/billingApi.js';
import { describeBillingOption } from '../src/features/billing/utils/billingPeriodPresentation.js';

const catalog = JSON.parse(readFileSync(new URL('../../backend/config/billing/standard_plan_catalog.json', import.meta.url), 'utf8'));
const amounts = { starter: [29, 87, 174], growth: [59, 177, 354], enterprise: [99, 297, 594] };

for (const locale of ['en', 'ar']) test(`launch catalog stays USD and undiscounted in ${locale} period presentation`, () => {
  const messages = JSON.parse(readFileSync(new URL(`../src/assets/locales/${locale}.json`, import.meta.url), 'utf8'));
  const t = (key, args = {}) => key.split('.').reduce((o, k) => o[k], messages).replace(/{{(\w+)}}/g, (_, k) => args[k]);
  for (const plan of catalog.plans) {
    assert.equal(plan.trial_days, 14);
    const defaults = plan.bootstrap_commercial_defaults;
    assert.equal(Number(defaults.monthly_price), amounts[plan.plan_key][0]);
    assert.ok(defaults.billing_periods.every(p => Number(p.discount_percent) === 0));
    const prices = ['monthly', 'three-months', 'six-months'].map((period_code, i) => ({
      period_code, interval_months: [1, 3, 6][i], amount: amounts[plan.plan_key][i],
      currency: 'USD', discount_percent: 0, purchasable: true,
    }));
    const mapped = mapPlan({ plan_key: plan.plan_key, trial_days: plan.trial_days, monthly_price: Number(defaults.monthly_price), currency: 'USD', prices });
    assert.equal(mapped.trialDays, 14);
    assert.equal(mapped.monthlyPrice, amounts[plan.plan_key][0]);
    assert.equal(mapped.currency, 'USD');
    for (const [period, price] of Object.entries(mapped.prices)) {
      assert.equal(price.monthlyEquivalent, amounts[plan.plan_key][0]);
      assert.equal(price.discountPercent, 0);
      const label = describeBillingOption({ period, months: price.months }, t);
      assert.ok(label.length > 0);
      assert.doesNotMatch(label, /10%|20%|١٠٪|٢٠٪/);
    }
  }
});
