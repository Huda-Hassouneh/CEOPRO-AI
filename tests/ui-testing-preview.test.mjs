import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { testingPlans, testingFeatures } from '../src/features/billing/api/uiTestingBillingData.js';
import { previewAdapter, setPreviewRole } from '../src/features/platform-admin/api/previewAdapter.js';

const source = (path) => readFileSync(new URL(`../${path}`, import.meta.url), 'utf8');

test('UI testing is explicitly gated behind Vite development and opt-in flag', () => {
  const mode = source('src/shared/config/uiTestingMode.js');
  assert.match(mode, /import\.meta\.env\.DEV\s*===\s*true/);
  assert.match(mode, /VITE_ENABLE_UI_TESTING_MODE\s*===\s*"true"/);
  assert.match(source('package.json'), /"dev:ui-test": "vite --mode ui-testing"/);
  assert.match(source('.env.ui-testing'), /^VITE_ENABLE_UI_TESTING_MODE=true/m);
});

test('all frontend guards use only the developer preview switch', () => {
  for (const path of [
    'src/app/router/ProtectedRoute.jsx',
    'src/app/router/OnboardingGuard.jsx',
    'src/app/router/RoleGuard.jsx',
    'src/features/billing/components/FeatureGate.jsx',
    'src/features/billing/components/FeatureRouteGuard.jsx',
    'src/features/platform-admin/components/PlatformAdminAccessGuard.jsx',
    'src/shared/components/layout/Sidebar.jsx',
  ]) assert.match(source(path), /UI_TESTING_MODE/, `${path} lacks test preview switch`);
});

test('preview catalog includes three distinct fictional USD plans with expected billing periods', () => {
  assert.equal(testingPlans.length, 3);
  assert.equal(new Set(testingPlans.map(p => p.id)).size, 3);
  for (const plan of testingPlans) {
    assert.equal(plan.isPreview, true);
    assert.equal(plan.currency, 'USD');
    assert.equal(plan.isActive, true);
    assert.deepEqual(plan.pricingOptions.map(o => o.period), ['monthly', 'three-months', 'six-months']);
    assert.ok(plan.pricingOptions.every(o => o.stripePriceId === null));
    assert.ok(plan.pricingOptions.every(o => o.monthlyEquivalent > 0));
  }
  assert.ok(testingFeatures.length >= 10);
});

test('existing admin preview adapter works without a real platform auth session', async () => {
  setPreviewRole('owner');
  const principal = await previewAdapter.me();
  assert.equal(principal.roleKey, 'owner');
  assert.equal(principal.permissions.all, true);
  const summary = await previewAdapter.list('overview');
  assert.equal(summary.preview, true);
  assert.ok(summary.companies > 0);
  setPreviewRole(null);
});

test('mutating calls are rejected by shared transport while in UI preview', () => {
  const transport = source('src/shared/lib/httpClient.js');
  assert.match(transport, /UI_TESTING_MODE\s*&&\s*!\["get", "head", "options"\]/);
  assert.match(transport, /UI_TESTING_READ_ONLY/);
  assert.match(source('src/features/platform-admin/api/platformAdminApi.js'), /ADMIN_PREVIEW = UI_TESTING_MODE/);
});
