import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { previewAxiosAdapter, getPreviewCompetitors } from '../src/shared/preview/uiPreviewApi.js';
import { previewSubscription, previewUsage, testingPlans } from '../src/features/billing/api/uiTestingBillingData.js';

const get = async (url, params = {}) => {
  const { data, status } = await previewAxiosAdapter({ url, method: 'get', params });
  assert.equal(status, 200);
  assert.equal(data.preview, true);
  return data.data;
};

test('dashboard uses complete fictional data for charts and KPI cards, with selectable periods', async () => {
  for (const periodDays of [7, 30, 90]) {
    const data = await get('/companies/undefined/dashboard', { periodDays });
    assert.equal(data.period.days, periodDays);
    assert.equal(data.salesOverview.points.length, periodDays);
    assert.ok(data.metrics.length >= 7);
    assert.equal(data.inventoryStatus.totals.totalItems, 248);
    assert.ok(data.demandForecast.rows.length > 0);
    assert.ok(data.competitorComparison.rows.length > 0);
  }
});

test('market and competitors are populated, and competitor details are navigable', async () => {
  const overview = await get('/market-intelligence', { periodDays: 30 });
  assert.ok(overview.products.length > 0);
  assert.ok(overview.metrics.length > 0);
  assert.ok(overview.competitors.length > 0);
  const rows = await get('/competitors');
  assert.deepEqual(rows, getPreviewCompetitors());
  const detail = await get(`/competitors/${rows[0].id}`);
  assert.equal(detail.id, rows[0].id);
  assert.ok(detail.mappedProducts.length > 0);
});

test('forecast overview, filtered products and detail render from matching fixtures', async () => {
  const overview = await get('/forecasting/demand', { productId: 'all', periodDays: 30 });
  assert.equal(overview.totalForecast.points.length, 30);
  assert.ok(overview.forecasts.length > 0);
  const id = overview.forecasts[0].id;
  const filtered = await get('/forecasting/demand', { productId: id, periodDays: 7 });
  assert.equal(filtered.forecasts.length, 1);
  const detail = await get(`/forecasting/demand/${id}`, { periodDays: 7 });
  assert.equal(detail.product.id, id);
  assert.equal(detail.filters.periodDays, 7);
});

test('documents and connectors show sample records without a backend', async () => {
  const connections = await get('/data-connection');
  assert.ok(connections.connectedSources.length > 0);
  assert.ok(connections.recentImports.length > 0);
  const docs = await get('/features/rag/documents', {page:1});
  assert.ok(docs.documents.length >= 2);
  assert.equal(docs.pagination.total, docs.documents.length);
});

test('billing has a preview subscription, usage, and USD plans', async () => {
  const subscription = (await previewSubscription()).data;
  assert.equal(subscription.status, 'active');
  assert.ok(testingPlans.some(plan => plan.id === subscription.planId));
  const usage = previewUsage();
  assert.ok(usage.entitlements.length >= 5);
  assert.equal(subscription.currency, 'USD');
});

test('preview rejects unknown reads and mutations instead of ever using network', async () => {
  await assert.rejects(get('/unrecognized-domain'), {code: 'UI_TESTING_FIXTURE_MISSING'});
  await assert.rejects(previewAxiosAdapter({url:'/subscription/checkout',method:'post'}), {code: 'UI_TESTING_READ_ONLY'});
  const source = readFileSync(new URL('../src/shared/lib/httpClient.js', import.meta.url),'utf8');
  assert.match(source, /config.adapter\s*=\s*previewAxiosAdapter/);
  assert.match(source, /delete config.headers.Authorization/);
});

test('hooks query without tenant auth only when developer preview is enabled', () => {
  for (const path of [
    '../src/features/forecasting/hooks/useDemandPrediction.js',
    '../src/features/forecasting/hooks/useForecastDetail.js',
    '../src/features/market-intelligence/hooks/useCompetitors.js',
    '../src/features/market-intelligence/hooks/useCompetitorProfile.js',
    '../src/features/market-intelligence/hooks/useCompetitorLeaderboard.js',
  ]) {
    const source = readFileSync(new URL(path,import.meta.url),'utf8');
    assert.match(source,/UI_TESTING_MODE/);
    assert.match(source,/enabled:.*UI_TESTING_MODE/);
  }
});
