import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const read = (path) => readFileSync(new URL(`../${path}`, import.meta.url), 'utf8');
const router = read('src/app/router/index.jsx');
const nav = read('src/shared/config/businessNavigation.js');
const sidebar = read('src/shared/components/layout/Sidebar.jsx');
const catalogPage = read('src/features/billing/pages/BillingCatalogPage.jsx');
const entitlements = read('src/features/billing/hooks/useEntitlements.js');
const rag = read('src/features/knowledge-base/components/RagChatWindow.jsx');
const competitor = read('src/features/market-intelligence/pages/AddCompetitorPage.jsx');
const connectData = read('src/features/data-connections/pages/ConnectDataPage.jsx');

for (const featureCode of [
  'dashboard_analytics',
  'market_intelligence',
  'demand_prediction',
  'rag_assistant',
  'data_integration',
]) assert.match(nav, new RegExp(`featureCode: '${featureCode}'`));

assert.match(sidebar, /business-sidebar__lock/);
assert.match(sidebar, /useEntitlements/);
assert.match(router, /FeatureRouteGuard featureCodes="dashboard_analytics"/);
assert.match(router, /FeatureRouteGuard featureCodes="market_intelligence"/);
assert.match(router, /FeatureRouteGuard featureCodes="demand_prediction"/);
assert.match(router, /FeatureRouteGuard featureCodes="rag_assistant"/);
assert.match(router, /FeatureRouteGuard featureCodes="data_integration"/);
assert.match(router, /FeatureRouteGuard featureCodes="report_generation"/);
assert.match(entitlements, /getFeatureState/);
assert.match(entitlements, /canConsume/);
assert.match(rag, /FeatureGate featureCode="rag_assistant" mode="consume"/);
assert.match(competitor, /FeatureGate featureCode="tracked_competitors" mode="consume"/);
assert.match(connectData, /FeatureGate featureCode="connected_data_sources" mode="consume"/);
assert.match(catalogPage, /unit_ar: form\.unit_ar/);
assert.match(catalogPage, /aggregation_type: form\.aggregation_type/);
assert.match(catalogPage, /reset_cycle: form\.reset_cycle/);

const teamSettings = read('src/features/settings/components/TeamSettings.jsx');
assert(teamSettings.includes("getFeatureState('team_members')"), 'Team member invitations must enforce team_members capacity');
assert(teamSettings.includes('FeatureLock'), 'Team member capacity needs visible locked-state UX');

console.log('Frontend entitlement integration verification passed.');
