import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { ownerBillingGroups, ownerBillingSelection } from '../src/features/billing/components/ownerBillingNavigation.js';

const tabs = ownerBillingGroups.flatMap(group => group.tabs);

test('owner workspaces retain existing deep-linked sections and promotions', () => {
  assert.deepEqual(ownerBillingGroups.map(group => group.id), ['plans', 'custom-plans', 'subscriptions', 'economics', 'promos']);
  for (const [tab, group] of [['plans','plans'], ['features','plans'], ['plan-features','plans'],
    ['custom-plans','custom-plans'], ['custom-quotes','custom-plans'], ['custom-pricing','custom-plans'],
    ['provider-accounting','economics'], ['pricing-studio','economics'], ['promos','promos']]) {
    assert.deepEqual(ownerBillingSelection(tab, tabs), {tab, group});
  }
  assert.deepEqual(ownerBillingSelection('unknown', tabs), {tab:'plans', group:'plans'});
});

test('workspace labels and authority explanations exist in both languages', () => {
  const load = locale => JSON.parse(readFileSync(new URL(`../src/assets/locales/${locale}.json`, import.meta.url), 'utf8')).billing.catalog.ownerNavigation;
  const en = load('en'), ar = load('ar');
  assert.deepEqual(Object.keys(en).sort(), Object.keys(ar).sort());
  for (const key of Object.keys(en)) assert.ok(en[key] && ar[key]);
});

test('owner permissions and alternate shell remain in place', () => {
  const page = readFileSync(new URL('../src/features/platform-admin/pages/BillingManagementPage.jsx', import.meta.url), 'utf8');
  const routes = readFileSync(new URL('../src/features/platform-admin/routes.jsx', import.meta.url), 'utf8');
  assert.match(page, /params\.get\('python'\) === '1'/);
  assert.match(page, /admin\.can\('billing\.manage'\)/);
  assert.match(page, /admin\.can\('billing\.pricing\.manage'\)/);
  assert.match(routes, /guarded\("billing\.read"/);
});
