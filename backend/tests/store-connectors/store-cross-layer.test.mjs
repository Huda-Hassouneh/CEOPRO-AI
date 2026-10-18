import test from 'node:test';
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {randomBytes} from 'node:crypto';
import {createServer} from 'node:net';
import {resolve} from 'node:path';
import {isolatedDatabase,tenantFixture} from '../isolated/database.mjs';

test('Node → authenticated Python service → WooCommerce adapter → restricted canonical database, repeated without duplicate sales',async()=>{
 const executable=process.env.KEEL_TEST_PYTHON||'python';
 const port=await new Promise(resolvePort=>{const s=createServer();s.listen(0,'127.0.0.1',()=>{const p=s.address().port;s.close(()=>resolvePort(p));});});
 const serviceSecret=randomBytes(32).toString('hex');
 const child=spawn(executable,[resolve('tests/store-connectors/provider_fixture.py'),String(port)],{cwd:resolve('../ai'),env:{...process.env,PYTHONPATH:resolve('../ai'),STORE_CONNECTOR_SERVICE_SECRET:serviceSecret},stdio:'ignore'});
 let f,prisma;try{
  for(let i=0;i<100;i++){try{if((await fetch(`http://127.0.0.1:${port}/health`)).ok)break;}catch{}if(i===99)throw Error('Python fixture did not start');await new Promise(r=>setTimeout(r,100));}
  f=await isolatedDatabase('ceopro_app',{maxConnections:10});await f.db.exec("SET TIME ZONE 'UTC'");const a=await tenantFixture(f.db);
  await f.db.exec(`INSERT INTO features(feature_code,feature_name,feature_name_ar,feature_type,aggregation_type,reset_cycle) VALUES('connected_data_sources','Sources','Sources','limit','max','lifetime') ON CONFLICT DO NOTHING;`);
  await f.db.query(`INSERT INTO plan_features(plan_id,feature_id,limit_value) SELECT $1,feature_id,1 FROM features WHERE feature_code='connected_data_sources'`,[a.planId]);
  await f.role('ceopro_app');process.env.DATABASE_URL=f.url;process.env.STORE_CONNECTOR_API_URL=`http://127.0.0.1:${port}`;process.env.STORE_CONNECTOR_SERVICE_SECRET=serviceSecret;process.env.STORE_CONNECTOR_ENCRYPTION_KEY=randomBytes(32).toString('hex');
  ({prisma}=await import('../../src/config/database.ts'));
  const {storeConnections:c}=await import('../../src/modules/dataconnection/store/connections.repo.ts');const {syncStorePage}=await import('../../src/modules/dataconnection/store/sync.repo.ts');
  const scope={tenantId:a.tenantId,userId:a.userId},url='https://store.example.test';
  assert.equal((await c.detect(scope,url)).supported,true);
  const connected=await c.connect(scope,{url,consumerKey:'ck_'+'a'.repeat(40),consumerSecret:'cs_'+'b'.repeat(40),consent:true,syncFrequencyMinutes:60});
  for(let i=0;i<2;i++){
   if(i)await c.sync(scope,connected.id);
   assert.equal((await syncStorePage(scope,connected.id)).status,'COMMITTED');assert.equal((await syncStorePage(scope,connected.id)).status,'COMMITTED');
  }
  await f.db.query("SELECT set_config('app.current_tenant_id',$1,false),set_config('app.current_user_id',$2,false)",[a.tenantId,a.userId]);
  const sales=(await f.db.query('SELECT quantity_sold,total_price FROM transactions WHERE tenant_id=$1',[a.tenantId])).rows;
  assert.equal(sales.length,1);assert.equal(sales[0].quantity_sold,2);assert.equal(Number(sales[0].total_price),4);
  const payloads=(await f.db.query('SELECT raw_payload_json FROM import_staging_rows WHERE tenant_id=$1',[a.tenantId])).rows;
  assert.ok(!JSON.stringify(payloads).includes('must-not-be-imported'));
  assert.equal((await c.status(scope,connected.id))[0].status,'CONNECTED');
  const inventory=(await f.db.query('SELECT stock_quantity FROM inventory WHERE tenant_id=$1',[a.tenantId])).rows;assert.equal(inventory.length,1);assert.equal(inventory[0].stock_quantity,31);
  const invoices=(await f.db.query('SELECT payment_status,total_amount FROM invoices WHERE tenant_id=$1',[a.tenantId])).rows;assert.equal(invoices.length,1);assert.equal(invoices[0].payment_status,'PAID');assert.equal(Number(invoices[0].total_amount),4);
 }finally{child.kill('SIGTERM');if(prisma)await prisma.$disconnect();if(f)await f.close();}
});
