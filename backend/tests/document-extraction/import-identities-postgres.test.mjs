import test from 'node:test';
import assert from 'node:assert/strict';
import {randomUUID} from 'node:crypto';
import {isolatedDatabase,tenantFixture} from '../isolated/database.mjs';
test('actual ingestion worker preserves sale identities across files and retries under restricted role',async()=>{
 const f=await isolatedDatabase('ceopro_ingestion_worker');let worker;
 try{
  const a=await tenantFixture(f.db),b=await tenantFixture(f.db);
  process.env.INGESTION_WORKER_DATABASE_URL=f.url;
  ({ingestionWorkerPrisma:worker}=await import('../../src/config/ingestion-worker-database.ts'));
  const {ingestionWorkerRepo:repo}=await import('../../src/modules/dataconnection/repo/ingestion-worker.repo.ts');
  const {extractCompleteSalesCsv}=await import('../../src/modules/dataconnection/service/sales-csv-import.ts');
  const header='product_name,quantity,unit_price,currency,transaction_date,sale_id,source_system\n';
  const line='Tea,2,10,JOD,2026-10-01,line-1,pos-a\n';
  async function run(tenant,csv){
   await f.role('postgres');
   const sourceId=randomUUID(),jobId=randomUUID();
   await f.db.query(`INSERT INTO data_sources(source_id,tenant_id,source_name,source_type,is_active) VALUES($1,$2,'Import','documents',false)`,[sourceId,tenant.tenantId]);
   await f.db.query(`INSERT INTO ingestion_jobs(job_id,tenant_id,source_id,job_status,processing_attempts) VALUES($1,$2,$3,'PROCESSING',1)`,[jobId,tenant.tenantId,sourceId]);
   for(const row of extractCompleteSalesCsv('sales.csv',Buffer.from(csv)).summary.row_outcomes)
    await f.db.query(`INSERT INTO import_staging_rows(tenant_id,job_id,raw_payload_json,validation_status) VALUES($1,$2,$3,'PENDING')`,[tenant.tenantId,jobId,JSON.stringify(row.parse_result.typed_fields)]);
   await f.role('ceopro_ingestion_worker');
   const result=await repo.processClaimedJob({job_id:jobId,tenant_id:tenant.tenantId,processing_attempts:1});
   assert(result);await f.role('postgres');
   return result;
  }
  assert.equal((await run(a,header+line+line)).committed,2);
  assert.equal((await f.db.query('SELECT count(*)::int AS n FROM transactions')).rows[0].n,1);
  await run(a,header+line); // Different job/file, same stable sale line.
  assert.equal((await f.db.query('SELECT count(*)::int AS n FROM transactions')).rows[0].n,1);
  assert.equal((await run(a,header+line.replace('Tea,2,','Tea,3,'))).quarantined,1);
  await run(a,header+line.replace('line-1','line-2'));
  await run(a,header+line.replace('pos-a','pos-b'));
  await run(b,header+line);
  await run(a,header+line.replace('line-1,pos-a',',' )+line.replace('line-1,pos-a',','));
  assert.equal((await f.db.query('SELECT count(*)::int AS n FROM transactions')).rows[0].n,6);
  assert.equal((await f.db.query('SELECT count(*)::int AS n FROM products')).rows[0].n,2);
  console.log('PASS: same/cross-file duplicates, conflicting IDs, distinct IDs, source systems, tenant isolation and legitimate identical legacy sales');
  await f.role('ceopro_app');
  await f.db.query("SELECT set_config('app.current_tenant_id',$1,false)",[a.tenantId]);
  assert.equal((await f.db.query('SELECT * FROM import_sale_identities WHERE tenant_id=$1',[b.tenantId])).rows.length,0);
  await assert.rejects(()=>f.db.query(`INSERT INTO import_sale_identities(tenant_id,source_system,sale_id,transaction_id,payload_sha256) VALUES($1,'x','x',$2,repeat('0',64))`,[a.tenantId,randomUUID()]),e=>e.code==='42501');
 }finally{if(worker)await worker.$disconnect();await f.close();}
});
