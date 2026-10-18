import test from 'node:test';
import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
import {readFileSync} from 'node:fs';
import {isolatedDatabase,tenantFixture} from '../isolated/database.mjs';
import {requestDiscovery,requestCompetitorDiscovery,requestCollection} from '../../src/modules/competitors/repo/market-tracking.requests.ts';
import {scheduleMarketSources,dispatchMarketEvent} from '../../src/modules/competitors/repo/market-dispatcher.repo.ts';
import {requireCompetitorAiActions} from '../../src/modules/competitors/service/competitor-capabilities.ts';
const forbidden=new Proxy({}, {get(){throw new Error('Disabled bridge attempted database access');}});
test('disabled producers and dispatcher perform no DB or Redis work even with old env enabled',async()=>{
 process.env.MARKET_TRACKING_ENABLED='true';
 assert.throws(requireCompetitorAiActions,e=>e.code==='NOT_IMPLEMENTED');
 assert.equal((await requestDiscovery(forbidden,'tenant')).eventId,null);
 assert.equal((await requestCompetitorDiscovery(forbidden,'tenant','competitor')).eventId,null);
 assert.equal(await requestCollection(forbidden,'tenant','source',60),null);
 assert.equal(await scheduleMarketSources(forbidden),0);
 assert.equal(await dispatchMarketEvent(forbidden,'redis://invalid'),null);
});
test('both root launchers and direct dispatcher exit before loading runtime DB configuration',()=>{
 for(const args of [['../scripts/keel.mjs','workers'],['../scripts/keel.mjs','dispatch'],['--import','tsx','src/workers/market-tracking.worker.ts']]){
  const result=spawnSync(process.execPath,args,{encoding:'utf8',env:{...process.env,DATABASE_URL:'invalid',MARKET_DISPATCHER_DATABASE_URL:'invalid',MARKET_TRACKING_ENABLED:'true'}});
  assert.equal(result.status,0,result.stderr);assert.match(result.stdout,/disabled/i);
 }
});
test('forward migration stops automatic imports from queuing custom work, retains data and tenant RLS',async()=>{
 const f=await isolatedDatabase('ceopro_app');
 try {
  const a=await tenantFixture(f.db),b=await tenantFixture(f.db);
  const trigger=(await f.db.query("SELECT tgenabled FROM pg_trigger WHERE tgname='sales_import_market_discovery'")).rows[0];
  assert.equal(trigger.tgenabled,'D');
  const source=(await f.db.query("INSERT INTO data_sources(tenant_id,source_name,source_type) VALUES($1,'Boundary fixture','manual') RETURNING source_id",[a.tenantId])).rows[0].source_id;
  await f.db.query("INSERT INTO ingestion_jobs(tenant_id,source_id,job_status,rows_processed) VALUES($1,$2,'PROCESSING',0)",[a.tenantId,source]);
  await f.db.query("UPDATE ingestion_jobs SET job_status='COMPLETED',rows_processed=3 WHERE tenant_id=$1",[a.tenantId]);
  assert.equal((await f.db.query('SELECT count(*)::int AS n FROM market_tracking_outbox')).rows[0].n,0);
  await f.db.exec(readFileSync(new URL('../../prisma/migrations/20261018180000_suspend_custom_market_bridge/migration.sql',import.meta.url),'utf8'));
  await f.role('ceopro_app');
  await f.db.query("SELECT set_config('app.current_tenant_id',$1,false),set_config('app.current_user_id',$2,false)",[a.tenantId,a.userId]);
  const products=(await f.db.query('SELECT tenant_id FROM products')).rows;
  assert.equal(products.length,1);assert.equal(products[0].tenant_id,a.tenantId);
  assert.equal((await f.db.query('SELECT product_id FROM products WHERE tenant_id=$1',[b.tenantId])).rows.length,0);
  await f.role('postgres');assert.equal((await f.db.query('SELECT count(*)::int AS n FROM products')).rows[0].n,2);
 }finally{await f.close();}
});
