import test from 'node:test';
import assert from 'node:assert/strict';
import {randomUUID,createHash} from 'node:crypto';
import {isolatedDatabase,tenantFixture,planFixture} from '../isolated/database.mjs';
test('runtime reserves, rolls back and refunds extraction against its original allocation',async()=>{
 const f=await isolatedDatabase('ceopro_app');let prisma;
 try{
  const t=await tenantFixture(f.db);
  await f.db.query(`UPDATE plan_features SET limit_value=2 WHERE plan_id=$1 AND feature_id=(SELECT feature_id FROM features WHERE feature_code='document_extraction')`,[t.planId]);
  process.env.DATABASE_URL=f.url;await f.role('ceopro_app');
  ({prisma}=await import('../../src/config/database.ts'));
  const {dataManagementRepo:repo}=await import('../../src/modules/dataconnection/repo/dataconnection.repo.ts');
  const input={tenantId:t.tenantId,userId:t.userId,jobId:randomUUID(),contentSha256:createHash('sha256').update('a').digest('hex'),fileName:'sales.csv',mimeType:'text/csv',fileSizeBytes:1025,extractionUsageKb:2};
  const reservation=await repo.reserveBusinessFileImport(input);
  const duplicate=await repo.reserveBusinessFileImport({...input,jobId:randomUUID()});
  assert.equal(duplicate.jobId,reservation.jobId);
  await assert.rejects(()=>repo.reserveBusinessFileImport({...input,jobId:randomUUID(),contentSha256:'b'.repeat(64)}),/usage limit/i);
  await f.role('postgres');
  assert.equal((await f.db.query('SELECT sum(current_usage)::int AS n FROM subscription_usage')).rows[0].n,2);
  assert.equal((await f.db.query('SELECT count(*)::int AS n FROM ingestion_jobs')).rows[0].n,1);
  await f.db.query(`UPDATE subscriptions SET status='canceled' WHERE id=$1`,[t.subscriptionId]);
  await planFixture(f.db,t.tenantId);
  await f.role('ceopro_app');
  await repo.markBusinessFileExtractionFailed({tenantId:t.tenantId,userId:t.userId,sourceId:reservation.sourceId,jobId:reservation.jobId});
  await repo.markBusinessFileExtractionFailed({tenantId:t.tenantId,userId:t.userId,sourceId:reservation.sourceId,jobId:reservation.jobId});
  await f.role('postgres');
  assert.equal((await f.db.query('SELECT sum(current_usage)::int AS n FROM subscription_usage')).rows[0].n,0);
  assert.equal((await f.db.query('SELECT job_status FROM ingestion_jobs')).rows[0].job_status,'FAILED');
  console.log('PASS quota exhaustion rolls back source/job; exact retry is not double charged; failure refunds original subscription once');
 }finally{if(prisma)await prisma.$disconnect();await f.close();}
});
