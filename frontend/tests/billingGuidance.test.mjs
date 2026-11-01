import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { displayUnit, featureGroup, featureUsageType, groupedFeatures } from '../src/features/billing/components/billingFeaturePresentation.js';
import { warningAction } from '../src/features/platform/pricingStudio.js';

test('feature grouping consumes canonical display metadata without changing identities; unknown rows remain visible', () => {
  const catalog = JSON.parse(readFileSync(new URL('../../backend/config/billing/standard_plan_catalog.json', import.meta.url)));
  const categories = new Map(catalog.categories.map(c => [c.key,c]));
  const rows = catalog.features.map(f => ({code:f.key,unit:f.unit,category:categories.get(f.category),display_order:f.display_order}));
  rows.push({code:'new_supported_code',unit:'request'});
  assert.equal(featureGroup(rows.find(f=>f.code==='ai_credits')),'automation');
  assert.equal(featureGroup(rows.at(-1)),'other');
  assert.equal(groupedFeatures(rows).flatMap(([, group])=>group).length,rows.length);
  assert.equal(featureUsageType(rows.find(f=>f.code==='ai_credits')),'credits');
  assert.equal(featureUsageType(rows.find(f=>f.code==='document_storage_mb')),'storage');
  assert.equal(featureUsageType({code:'market_intelligence',type:'boolean'}),'boolean');
  assert.equal(featureUsageType({code:'monthly_reports',aggregationType:'sum'}),'consumable');
});

test('canonical units have localized presentation without changing their technical units',()=>{
  const ar=JSON.parse(readFileSync(new URL('../src/assets/locales/ar.json',import.meta.url),'utf8'));
  const t=key=>key.split('.').reduce((v,k)=>v?.[k],ar);
  assert.equal(displayUnit('credits',t),ar.billing.customPlan.unitNames.credit);
  assert.equal(displayUnit('KB',t),ar.common.units.kilobytes);
  assert.equal(displayUnit('unknown_runtime_unit',t),'unknown_runtime_unit');
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
