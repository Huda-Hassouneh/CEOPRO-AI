import assert from 'node:assert/strict';import {test} from 'node:test';import {readFileSync} from 'node:fs';
const read=path=>readFileSync(new URL('../../'+path,import.meta.url),'utf8');
test('bridge stores requests transactionally, retains RLS and limits dispatcher privileges',()=>{
 const sql=read('prisma/migrations/20261013200000_market_tracking_dispatch/migration.sql');
 assert.match(sql,/UNIQUE\(tenant_id,dedupe_key\)/);assert.match(sql,/FORCE ROW LEVEL SECURITY/);assert.match(sql,/NOBYPASSRLS/);assert.match(sql,/AFTER UPDATE OF job_status,rows_processed/);assert.match(sql,/GRANT UPDATE\(sync_frequency_minutes\)/);
 assert.doesNotMatch(sql,/GRANT .*connection_credentials_vault|INSERT INTO competitor_prices|DISABLE ROW LEVEL SECURITY/);
 const repo=read('src/modules/competitors/repo/market-dispatcher.repo.ts');assert.match(repo,/WEB_SCRAPE/);assert.match(repo,/FOR UPDATE SKIP LOCKED/);assert.match(repo,/COST_GUARD_NOT_CONFIGURED/);assert.match(repo,/m.is_active AND m.comparison_confirmed AND tc.is_tracked/);assert.match(repo,/committed_table='transactions'/);
});
