import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { featureGroup, featureUsageType, groupedFeatures } from '../src/features/billing/components/billingFeaturePresentation.js';
import { warningAction } from '../src/features/platform/pricingStudio.js';

test('feature grouping only classifies known executable codes; unknown catalog rows remain visible', () => {
  const rows = [{code:'ai_credits',unit:'credits'}, {code:'document_storage_mb',unit:'MB'}, {code:'new_supported_code',unit:'request'}];
  assert.equal(featureGroup('ai_credits'),'intelligence');
  assert.equal(featureGroup('new_supported_code'),'other');
  assert.equal(groupedFeatures(rows).flatMap(([, group])=>group).length,rows.length);
  assert.equal(featureUsageType(rows[0]),'credits');
  assert.equal(featureUsageType(rows[1]),'storage');
  assert.equal(featureUsageType({code:'market_intelligence',type:'boolean'}),'boolean');
});

test('incomplete Studio evidence points to the responsible owner configuration area', () => {
  assert.equal(warningAction('POLICY_MISSING'),'policy');
  assert.equal(warningAction('RATE_UNVERIFIED'),'provider-accounting');
  assert.equal(warningAction('RATE_MISSING'),'rate-or-binding');
  assert.equal(warningAction('COST_MULTIPLIER_MISSING'),'custom-quotes');
  assert.equal(warningAction('CREDIT_BUDGET_UNAVAILABLE'),'plan-features');
  assert.equal(warningAction('CURRENT_PRICE_UNSAFE'),null);
});

test('all nine tab guides, statuses and setup steps have English and Arabic content', () => {
  const keys = object => Object.entries(object).flatMap(([key,value]) => typeof value==='object' ? keys(value).map(child=>`${key}.${child}`) : [key]).sort();
  const en = JSON.parse(readFileSync(new URL('../src/assets/locales/en.json',import.meta.url),'utf8')).billing;
  const ar = JSON.parse(readFileSync(new URL('../src/assets/locales/ar.json',import.meta.url),'utf8')).billing;
  assert.deepEqual(keys(en.catalog.guided),keys(ar.catalog.guided));
  assert.deepEqual(keys(en.pricingStudio),keys(ar.pricingStudio));
  assert.deepEqual(keys(en.providerAccounting),keys(ar.providerAccounting));
  assert.equal(Object.keys(en.catalog.guided.tabs).length,9);
});
