import test from 'node:test';
import assert from 'node:assert/strict';
import {randomUUID} from 'node:crypto';
import {isolatedDatabase,tenantFixture} from '../isolated/database.mjs';
test('BYTEA storage, quota rollback, delete/reclaim, downgrade and tenant isolation as ceopro_app',async()=>{
 const f=await isolatedDatabase('ceopro_app');let prisma;
 try{
  const a=await tenantFixture(f.db),b=await tenantFixture(f.db);process.env.DATABASE_URL=f.url;
  await f.role('ceopro_app');({prisma}=await import('../../src/config/database.ts'));
  const repo=await import('../../src/modules/rag/repo/rag.repo.ts');
  const {ensureRagSearchIndex}=await import('../../src/modules/rag/service/rag-search.service.ts');
  const save=(tenant,bytes)=>repo.saveUploadedRagDocument({tenantId:tenant.tenantId,userId:tenant.userId,documentId:randomUUID(),fileName:'source.txt',fileSizeBytes:1,contentType:'text/plain',sourceFileContent:Buffer.alloc(bytes,65),processedStatus:'Stored',extractionUsageKb:Math.max(1,Math.ceil(bytes/1024))});
  const first=await save(a,600*1024);
  assert.equal(Number(first.file_size_bytes),600*1024);assert.equal(first.processed_status,'Stored');
  assert.equal((await repo.getRagStorage(a)).usedBytes,600*1024);
  await assert.rejects(()=>save(a,600*1024),/DOCUMENT_STORAGE_CAPACITY_EXCEEDED/);
  await f.role('postgres');
  assert.equal((await f.db.query('SELECT sum(current_usage)::int AS n FROM subscription_usage')).rows[0].n,600);
  await f.role('ceopro_app');
  const sources=await repo.persistRagQuerySources({...a,sources:[{documentId:first.document_id,text:'Citation'}]});assert.equal(sources.length,1);
  assert.equal((await repo.deleteStoredRagDocument({...b,documentId:first.document_id})).status,'not_found');
  assert.equal((await repo.getRagQueryDocuments({...b,limit:10})).length,0);
  assert.equal((await repo.deleteStoredRagDocument({...a,documentId:first.document_id})).status,'deleted');
  assert.equal((await repo.getRagStorage(a)).usedBytes,0);
  await assert.rejects(()=>repo.persistRagQuerySources({...a,sources:[{documentId:first.document_id,text:'Stale citation'}]}),/removed/);
  await f.role('postgres');assert.equal((await f.db.query('SELECT count(*)::int AS n FROM rag_document_chunks')).rows[0].n,0);
  await f.role('ceopro_app');
  const exact=await save(a,1048576);await assert.rejects(()=>save(a,1),/CAPACITY_EXCEEDED/);
  await f.role('postgres');
  await f.db.query(`UPDATE plan_features SET limit_value=0 WHERE plan_id=$1 AND feature_id=(SELECT feature_id FROM features WHERE feature_code='document_storage_mb')`,[a.planId]);
  await f.role('ceopro_app');assert.equal((await repo.getRagStorage(a)).isOverLimit,true);await assert.rejects(()=>save(a,1),/CAPACITY_EXCEEDED/);
  await ensureRagSearchIndex(a);
  assert.equal((await repo.getRagQueryDocuments({...a,limit:10})).length,1); // Existing data survives a downgrade.
  await f.role('postgres');await f.db.query(`UPDATE subscriptions SET status='canceled' WHERE id=$1`,[a.subscriptionId]);await f.role('ceopro_app');
  assert.equal((await repo.deleteStoredRagDocument({...a,documentId:exact.document_id})).status,'deleted');
  const status=await repo.getRagStorage(a);assert.equal(status.included,false);assert.equal(status.usedBytes,0);
  await f.role('postgres');
  await f.db.query(`INSERT INTO rag_documents_metadata(document_id,tenant_id,file_name,storage_bucket_path,file_size_bytes) VALUES($1,$2,'External','tenant/object.txt',123)`,[randomUUID(),b.tenantId]);
  await f.db.query(`INSERT INTO rag_documents_metadata(document_id,tenant_id,file_name,storage_bucket_path,file_size_bytes) VALUES($1,$2,'Missing bytes','ceopro-db://legacy',1000)`,[randomUUID(),b.tenantId]);
  await f.role('ceopro_app');assert.equal((await repo.getRagStorage(b)).usedBytes,123);
  const external=(await repo.listRagDocuments({...b,page:1,pageSize:10})).find(d=>d.file_name==='External');
  assert.equal((await repo.deleteStoredRagDocument({...b,documentId:external.document_id})).status,'external');
  await f.role('postgres');
  await f.db.query(`INSERT INTO rag_documents_metadata(document_id,tenant_id,file_name,storage_bucket_path,file_size_bytes,processed_status)
    VALUES($1,$2,'Legacy shared summary','_generated/sales_history.txt',10,'Processed')`,[randomUUID(),b.tenantId]);
  await f.role('ceopro_app');assert.equal((await repo.getRagQueryDocuments({...b,limit:10})).length,0);
  console.log('PASS actual byte usage, exact boundary, capacity failure rolls back extraction, tenant-scoped deletion, chunk cascade, stale query rejection, downgrade/cancellation, conservative external accounting');
 }finally{if(prisma)await prisma.$disconnect();await f.close();}
});
