import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {test} from 'node:test';
const read=file=>readFileSync(new URL(`../../${file}`,import.meta.url),'utf8');
test('direct database tracking uses common serialized capacity guard and preserves existing history',()=>{
 const sql=read('prisma/migrations/20261013180000_competitor_management_integrity/migration.sql');
 assert.match(sql,/BEFORE INSERT OR UPDATE OF tenant_id, is_tracked/);
 assert.match(sql,/pg_advisory_xact_lock/);assert.match(sql,/read committed/);assert.match(sql,/current_usage >= capacity.limit_value/);
 assert.match(sql,/status IN \('active', 'trialing'\)/);assert.match(sql,/f.feature_code = 'tracked_competitors'/);
 assert.match(sql,/public.get_current_tenant\(\) IS DISTINCT FROM request_tenant/);
 assert.doesNotMatch(sql,/DELETE FROM|DROP TABLE|DISABLE ROW LEVEL SECURITY/);
 assert.match(sql,/comparison_confirmed BOOLEAN NOT NULL DEFAULT FALSE/);
});
test('list retains existing array contract, adds metadata and all mutations use authenticated tenant controller',()=>{
 const controller=read('src/modules/competitors/controller/competitors.controller.ts');
 assert.match(controller,/data:list.competitors,meta:/);
 assert.match(controller,/tenantId:req.tenant_id,userId:req.user.id/);
 const route=read('src/modules/competitors/route/competitors.route.ts');
 assert.match(route,/router.use\(authenticateUser,requireTenant\)/);
 for(const operation of ['update','track','schedule','confirm']) assert.ok(route.includes(`handleCompetitor('${operation}')`));
});
test('supported add form persists and only sends supported competitor fields',()=>{
 const page=read('../frontend/src/features/market-intelligence/pages/AddCompetitorPage.jsx');
 assert.match(page,/mutation.mutateAsync\(values\)/);assert.doesNotMatch(page,/addPreviewCompetitor/);
 const form=read('../frontend/src/features/market-intelligence/components/AddCompetitorForm.jsx');
 assert.doesNotMatch(form,/amazon|shopify|linkedin/);
});
test('new translation keys have parity and contain every comparison reason',()=>{
 const en=JSON.parse(read('../frontend/src/assets/locales/en.json')),ar=JSON.parse(read('../frontend/src/assets/locales/ar.json'));
 assert.deepEqual(Object.keys(en.competitorManagement).sort(),Object.keys(ar.competitorManagement).sort());
 for(const reason of ['NO_PRICE','MATCH_UNCONFIRMED','SOURCE_BLOCKED','STALE_PRICE','CURRENCY_MISMATCH','INVALID_DATE']) assert.ok(en.competitorManagement[reason]&&ar.competitorManagement[reason]);
});
