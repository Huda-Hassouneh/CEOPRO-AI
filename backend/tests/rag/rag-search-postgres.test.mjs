import test,{mock} from 'node:test';
import assert from 'node:assert/strict';
import {randomUUID} from 'node:crypto';
import {isolatedDatabase,tenantFixture} from '../isolated/database.mjs';
import {docxFixture,pdfFixture,xlsxFixture} from './search-fixtures.ts';

test('restricted runtime retrieves old relevant files across the entire tenant corpus, not just newest ten',async()=>{
 const f=await isolatedDatabase('ceopro_app');let prisma;
 const sent=[];
 try {
  const a=await tenantFixture(f.db),b=await tenantFixture(f.db);
  await f.db.exec(`INSERT INTO features(feature_code,feature_name,feature_name_ar,feature_type,aggregation_type,reset_cycle)
    VALUES('rag_assistant','RAG','RAG','limit','sum','billing_period') ON CONFLICT(feature_code) DO NOTHING`);
  await f.db.query(`INSERT INTO plan_features(plan_id,feature_id,limit_value) SELECT $1,feature_id,100000 FROM features WHERE feature_code='rag_assistant'`,[a.planId]);
  process.env.DATABASE_URL=f.url;await f.role('ceopro_app');
  ({prisma}=await import('../../src/config/database.ts'));
  await mock.module('../../src/modules/rag/client/rag.client.ts',{namedExports:{
   isRagClientError:()=>false,
   queryRagAi:async input=>{
    sent.push(input);const first=input.documents[0];
    return {answer:'Zephyr delivery fee is 7 JOD.',sources:[{source_index:1,document:first.file_name,chunk_index:0,text:'Zephyr delivery fee is 7 JOD.',score:1}],token_usage:{prompt_tokens:5,completion_tokens:5,total_tokens:10}};
   }
  }});
  const repo=await import('../../src/modules/rag/repo/rag.repo.ts');
  const {ensureRagSearchIndex}=await import('../../src/modules/rag/service/rag-search.service.ts');
  const {searchRevision,extractSearchContent}=await import('../../src/modules/rag/service/rag-search-text.ts');
  const {queryRag}=await import('../../src/modules/rag/service/rag.service.ts');
  const save=async(tenant,fileName,buffer)=>repo.saveUploadedRagDocument({...tenant,documentId:randomUUID(),fileName,
    fileSizeBytes:buffer.length,contentType:'application/octet-stream',sourceFileContent:buffer,processedStatus:'Stored',extractionUsageKb:Math.max(1,Math.ceil(buffer.length/1024))});
  const old=await save(a,'record-a.txt',Buffer.from('Zephyr delivery fee is 7 JOD.'));
  const oldPdf=await save(a,'record-b.pdf',pdfFixture('Nebula refunds allowed within 9 days'));
  const oldDocx=await save(a,'record-c.docx',docxFixture('Orion refunds require original packaging'));
  const oldXlsx=await save(a,'record-d.xlsx',xlsxFixture());
  const arabic=await save(a,'record-e.md',Buffer.from('سعر الأرز الأبيض خمسة دنانير'));
  const oldIds=[old,oldPdf,oldDocx,oldXlsx,arabic].map(d=>d.document_id);
  for(let i=0;i<18;i++)await save(a,`fresh-${i}.txt`,Buffer.from('Routine produce report: apples and bananas.'));
  const foreign=await save(b,'foreign.txt',Buffer.from('Zephyr delivery fee is SECRET 999 JOD.'));
  await f.role('postgres');
  for(const id of oldIds)await f.db.query(`UPDATE rag_documents_metadata SET uploaded_at='2001-01-01' WHERE document_id=$1`,[id]);
  const newest=(await f.db.query('SELECT document_id FROM rag_documents_metadata WHERE tenant_id=$1 ORDER BY uploaded_at DESC,document_id DESC LIMIT 10',[a.tenantId])).rows;
  assert.ok(newest.every(d=>!oldIds.includes(d.document_id)));
  await f.role('ceopro_app');
  await ensureRagSearchIndex(a);
  for(const [question,id] of [
    ['What is the Zephyr delivery fee?',old.document_id],
    ['Nebula refund policy',oldPdf.document_id],
    ['Orion original packaging',oldDocx.document_id],
    ['Who supplies ORCHID-5?',oldXlsx.document_id],
    ['ما سعر الارز الابيض؟',arabic.document_id]
  ]) {
    const selected=await repo.getRagQueryDocuments({...a,queryText:question,limit:10});
    assert.equal(selected.length,10);
    if(selected[0].document_id!==id) {
      await f.role('postgres');
      console.log('Ranking diagnostic',question,selected.map(d=>d.file_name),
        (await f.db.query('SELECT d.file_name,s.content_state,p.search_text FROM rag_documents_metadata d LEFT JOIN rag_document_search s USING(tenant_id,document_id) LEFT JOIN rag_document_search_passages p USING(tenant_id,document_id) WHERE d.document_id=$1',[id])).rows);
      await f.role('ceopro_app');
    }
    assert.equal(selected[0].document_id,id,question);
    assert.ok(selected.every(d=>d.document_id!==foreign.document_id));
  }
  // The source-selection fix is exercised through queryRag too. Only the external
  // provider is simulated; database, roles, entitlements, citations and usage are real.
  const result=await queryRag({...a,queryText:'What is the Zephyr delivery fee?',topK:5});
  assert.equal(result.answer,'Zephyr delivery fee is 7 JOD.');
  assert.equal(sent.length,1);assert.equal(sent[0].documents.length,10);
  assert.ok(sent[0].documents[0].file_name.startsWith(old.document_id));
  assert.equal(sent[0].documents[0].text,'Zephyr delivery fee is 7 JOD.');
  assert.ok(!JSON.stringify(sent[0]).includes('SECRET'));
  assert.equal(result.sources.length,1);
  await queryRag({...a,queryText:'And how much is that?',topK:5,sessionId:result.session_id,requestId:randomUUID()});
  assert.ok(sent.at(-1).documents[0].file_name.startsWith(old.document_id),'follow-up retains the older source through saved conversation context');
  assert.equal(sent.at(-1).history.length,2);

  await f.role('postgres');
  assert.equal((await f.db.query('SELECT count(*)::int AS n FROM rag_document_search WHERE tenant_id=$1',[a.tenantId])).rows[0].n,23);
  assert.equal((await f.db.query('SELECT count(*)::int AS n FROM rag_document_search WHERE tenant_id=$1',[b.tenantId])).rows[0].n,0);
  const indexed=(await f.db.query('SELECT indexed_at FROM rag_document_search WHERE document_id=$1',[old.document_id])).rows[0].indexed_at;
  await f.role('ceopro_app');await ensureRagSearchIndex(a);
  await f.role('postgres');assert.equal(String((await f.db.query('SELECT indexed_at FROM rag_document_search WHERE document_id=$1',[old.document_id])).rows[0].indexed_at),String(indexed));
  await f.role('ceopro_app');
  // RLS protects both the checkpoint and passage tables, even with a forged tenant ID.
  await prisma.$transaction(async tx=>{
    await tx.$executeRaw`SELECT set_config('app.current_tenant_id',${a.tenantId},true),set_config('app.current_user_id',${a.userId},true)`;
    for(const table of ['rag_document_search','rag_document_search_passages']) {
      const rows=await tx.$queryRawUnsafe(`SELECT count(*)::int AS n FROM public.${table} WHERE tenant_id=$1::uuid`,b.tenantId);
      assert.equal(rows[0].n,0);
    }
  });
  await assert.rejects(()=>prisma.$transaction(async tx=>{
    await tx.$executeRaw`SELECT set_config('app.current_tenant_id',${a.tenantId},true),set_config('app.current_user_id',${a.userId},true)`;
    await tx.$executeRaw`INSERT INTO rag_document_search(tenant_id,document_id,index_version,content_state) VALUES(${b.tenantId}::uuid,${foreign.document_id}::uuid,1,'ready')`;
  }),/row-level security/);
  // Replacements invalidate existing text; lazy backfill must not retain stale facts.
  await f.role('postgres');
  await f.db.query(`UPDATE rag_documents_metadata SET source_file_content=$1 WHERE document_id=$2`,[Buffer.from('Vega delivery fee is now 4 JOD.'),old.document_id]);
  assert.equal((await f.db.query('SELECT count(*)::int AS n FROM rag_document_search WHERE document_id=$1',[old.document_id])).rows[0].n,0);
  await f.role('ceopro_app');
  const snapshot=(await repo.getUnindexedRagDocuments(a)).find(d=>d.document_id===old.document_id);
  await ensureRagSearchIndex(a);
  assert.equal((await repo.getRagQueryDocuments({...a,queryText:'Vega delivery fee',limit:10}))[0].document_id,old.document_id);
  await f.role('postgres');await f.db.query(`UPDATE rag_documents_metadata SET file_name='changed.txt' WHERE document_id=$1`,[old.document_id]);await f.role('ceopro_app');
  assert.equal(await repo.saveRagSearchContent({...a,document:snapshot,revision:searchRevision(snapshot),content:await extractSearchContent(snapshot)}),false);
  await ensureRagSearchIndex(a);
  assert.equal((await repo.deleteStoredRagDocument({...a,documentId:old.document_id})).status,'deleted');
  assert.equal(await repo.saveRagSearchContent({...a,document:snapshot,revision:searchRevision(snapshot),content:await extractSearchContent(snapshot)}),false);
  await f.role('postgres');
  assert.equal((await f.db.query('SELECT count(*)::int AS n FROM rag_document_search_passages WHERE document_id=$1',[old.document_id])).rows[0].n,0);
  for(const row of (await f.db.query(`SELECT relrowsecurity,relforcerowsecurity FROM pg_class WHERE relname IN ('rag_document_search','rag_document_search_passages')`)).rows){assert.equal(row.relrowsecurity,true);assert.equal(row.relforcerowsecurity,true);}
  console.log('PASS old TXT/PDF/DOCX/XLSX/Arabic retrieval, 23-document backfill, 10-document provider request, tenant isolation, stable indexing, invalidation, stale-source and deletion checks');
 }finally{mock.restoreAll();if(prisma)await prisma.$disconnect();await f.close();}
});
