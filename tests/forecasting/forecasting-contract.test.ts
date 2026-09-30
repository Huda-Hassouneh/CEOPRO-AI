import assert from 'node:assert/strict';
import { test } from 'node:test';
import { readFileSync } from 'node:fs';
// Database boundary is replaced before calls. No network/database connection is made.
process.env.DATABASE_URL = 'postgresql://test:test@127.0.0.1:1/test';
const { prisma } = await import('../../src/config/database.js');
const { getDemandOverview, getDemandDetail } = await import('../../src/modules/forecasting/service/forecasting.service.js');
const { parseForecastQuery, getOverview, getDetail } = await import('../../src/modules/forecasting/controller/forecasting.controller.js');
const tenant = '11111111-1111-4111-8111-111111111111';
const productId = '22222222-2222-4222-8222-222222222222';
const userId = '33333333-3333-4333-8333-333333333333';
const now = new Date();
const start = new Date(now.toISOString().slice(0, 10) + 'T00:00:00Z');
const day = (n: number) => new Date(start.getTime() + n * 86400000);
const forecasts = Array.from({ length: 7 }, (_, i) => ({ forecast_id: String(i), product_id: productId, forecast_start_date: null, forecast_end_date: null, forecast_target_date: day(i), expected_demand: i,
 confidence_range_lower: null, confidence_range_upper: null, created_at: day(-1), model_version: 'test', recommendation_outcomes: [] }));
const stock = [{ product_id: productId, stock_quantity: 3, safety_stock: 1 }, { product_id: productId, stock_quantity: 4, safety_stock: 2 }];
const product = { product_id: productId, product_name: { en: 'Test', ar: 'اختبار' }, category: null };
let queries = 0;
const assertScope = (args: any) => { assert.equal(args.where.tenant_id, tenant); queries++; };
const originalTransaction = prisma.$transaction;
(prisma as any).$transaction = async (fn: any) => fn({
 $queryRaw: async (parts: TemplateStringsArray, ...values: unknown[]) => {
   const sql = parts.join('?');
   assert.ok(values.includes(tenant));
   if (sql.includes('set_config')) { assert.ok(values.includes(userId)); return []; }
   assert.ok(values.includes(productId)); return [{ date: day(-1).toISOString().slice(0, 10), units: 9n }];
 },
 products: { findMany: async (args: any) => { assertScope(args); assert.equal(args.where.deleted_at, null); return [product]; } },
 inventory: { findMany: async (args: any) => { assertScope(args); return stock; } },
 demand_forecasts: { findMany: async (args: any) => { assertScope(args); assert.equal(args.include.recommendation_outcomes.where.tenant_id, tenant); return forecasts; } }
});
test('strict query validation rejects invalid horizons, arrays and UUIDs', () => {
 for (const value of ['7days', '-1', '0', '365', ['7'], {}, '']) assert.equal(parseForecastQuery(value, 'all'), null);
 assert.deepEqual(parseForecastQuery(undefined, undefined), { periodDays: 30, productId: 'all' });
 assert.equal(parseForecastQuery('7', 'invalid'), null); assert.equal(parseForecastQuery('7', 'all', false), null);
});
test('overview/detail share totals, stock aggregation and unknown accuracy; all reads scoped', async () => {
 const overview = await getDemandOverview(tenant, 7, productId, userId);
 const detail = await getDemandDetail(tenant, productId, userId, 7);
 assert.equal(overview!.forecasts[0]!.expectedDemand, 21);
 assert.equal(overview!.forecasts[0]!.currentStock, 7);
 assert.equal(detail!.metrics.find(m => m.id === 'expectedDemand')!.value, 21);
 assert.equal(detail!.aiInsight, null); assert.equal(detail!.recommendation, null);
 assert.equal(detail!.metrics.find(m => m.id === 'modelAccuracy')!.value, null);
 assert.equal(detail!.chart.points.find(p => p.date === day(-1).toISOString().slice(0, 10))!.actual, 9);
 assert.equal(detail!.chart.points[0]!.actual, null);
 assert.equal(overview!.products.length, 1); assert.ok(queries >= 6);
});
test('other-tenant or deleted product IDs never resolve to a product', async () => {
 assert.equal(await getDemandOverview(tenant, 7, '44444444-4444-4444-8444-444444444444', userId), null);
 assert.equal(await getDemandDetail(tenant, '44444444-4444-4444-8444-444444444444', userId), null);
});
test('controller responds with 400 for malformed inputs and 404 for absent products', async () => {
 const response: any = { code: 0, status(n: number) { this.code = n; return this; }, json() { return this; } };
 const request: any = { tenant_id: tenant, user: { id: userId }, query: { periodDays: '7garbage' }, params: {} };
 const next = (error?: unknown) => { if (error) throw error; };
 await getOverview(request, response, next); assert.equal(response.code, 400);
 request.query = {}; request.params.productId = '44444444-4444-4444-8444-444444444444';
 await getDetail(request, response, next); assert.equal(response.code, 404);
});
test('every forecasting route is behind authentication, membership and boolean access', () => {
 const source = readFileSync(new URL('../../src/modules/forecasting/route/forecasting.route.ts', import.meta.url), 'utf8');
 assert.ok(source.includes('router.use(authenticateUser, requireTenant, requireFeatureAccess("demand_prediction"))'));
 assert.ok(source.indexOf('router.use') < source.indexOf('router.get'));
});
process.on('exit', () => { (prisma as any).$transaction = originalTransaction; });
test('boolean entitlement middleware blocks missing subscription/feature and allows inclusion without metering', async () => {
 const { requireFeatureAccess } = await import('../../src/validators/validateFeatures.js');
 const original = prisma.subscription.findFirst;
 let subscription: any = null;
 (prisma.subscription as any).findFirst = async (args: any) => { assert.equal(args.where.tenantId, tenant); return subscription; };
 const res: any = { code: 0, status(n: number) { this.code = n; return this; }, json() { return this; } };
 let allowed = false;
 const req: any = { tenant_id: tenant };
 const middleware = requireFeatureAccess('demand_prediction');
 try {
   await middleware(req, res, () => { allowed = true; }); assert.equal(allowed, false);
   subscription = { plan: { planFeatures: [] } };
   await middleware(req, res, () => { allowed = true; }); assert.equal(res.code, 403); assert.equal(allowed, false);
   subscription = { plan: { planFeatures: [{ feature: { code: 'demand_prediction', type: 'boolean' } }] } };
   await middleware(req, res, () => { allowed = true; }); assert.equal(allowed, true);
 } finally { prisma.subscription.findFirst = original; }
});
test('persisted restock uses its own forecast, all warehouse safety stock, and clamps at zero', async () => {
 const first = forecasts[0]!;
 const recommendations = first.recommendation_outcomes as any[];
 const originalDemand = first.expected_demand;
 recommendations.push({ recommendation_id: 'r', recommended_action: 'restock', created_at: now });
 try {
   first.expected_demand = 10;
   let detail = await getDemandDetail(tenant, productId, userId, 7);
   assert.equal(detail!.recommendation!.suggestedQuantity, 6); // 10 + (1+2) - (3+4)
   first.expected_demand = 0;
   detail = await getDemandDetail(tenant, productId, userId, 7);
   assert.equal(detail!.recommendation!.suggestedQuantity, 0);
   assert.equal(detail!.recommendation!.priority, null);
 } finally { first.expected_demand = originalDemand; recommendations.length = 0; }
});
