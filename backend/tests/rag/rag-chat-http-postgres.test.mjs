import test,{mock} from 'node:test';import assert from 'node:assert/strict';
import express from 'express';import bcrypt from 'bcrypt';import {randomBytes,randomUUID} from 'node:crypto';
import {isolatedDatabase,tenantFixture} from '../isolated/database.mjs';
import {readFile} from 'node:fs/promises';
test('real HTTP login, multipart upload, saved chat, citations, quota replay and reindex under ceopro_app',async()=>{
 const f=await isolatedDatabase('ceopro_app');let prisma,server;
 try{
  const a=await tenantFixture(f.db),b=await tenantFixture(f.db),password='RagHttpFixturePass123!';
  for(const t of [a,b])await f.db.query(`UPDATE users SET password_hash=$1 WHERE user_id=$2`,[await bcrypt.hash(password,10),t.userId]);
  await f.db.exec(`INSERT INTO features(feature_code,feature_name,feature_name_ar,feature_type,aggregation_type,reset_cycle) VALUES('rag_assistant','RAG','RAG','limit','sum','billing_period') ON CONFLICT(feature_code) DO NOTHING`);
  for(const t of [a,b])await f.db.query(`INSERT INTO plan_features(plan_id,feature_id,limit_value) SELECT $1,feature_id,12 FROM features WHERE feature_code='rag_assistant'`,[t.planId]);
  process.env.DATABASE_URL=f.url;process.env.JWT_SECRET=randomBytes(32).toString('hex');await f.role('ceopro_app');
  ({prisma}=await import('../../src/config/database.ts'));
  let calls=0;
  await mock.module('../../src/modules/rag/client/rag.client.ts',{namedExports:{isRagClientError:()=>false,queryRagAi:async input=>{
   calls++;return {answer:'Delivery costs 7 JOD.',sources:[{source_index:1,document:input.documents[0].file_name,chunk_index:0,text:'Zephyr delivery costs 7 JOD.',score:1}],token_usage:{total_tokens:6}};
  }}});
  const {default:auth}=await import('../../src/modules/auth/route/auth.route.ts');const {default:rag}=await import('../../src/modules/rag/route/rag.route.ts');
  const app=express();app.use(express.json());app.use('/auth',auth);app.use('/features/rag',rag);app.use((e,_req,res,_next)=>res.status(500).json({message:e.message}));
  server=await new Promise(resolve=>{const s=app.listen(0,'127.0.0.1',()=>resolve(s));});const base=`http://127.0.0.1:${server.address().port}`;
  const login=async t=>{
   const r=await fetch(base+'/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({email:`${t.userId}@example.test`,password})});
   const j=await r.json();assert.equal(r.status,200,JSON.stringify(j));return {Authorization:`Bearer ${j.session.accessToken}`};
  };
  const headers=await login(a),other=await login(b);
  assert.equal((await fetch(base+'/features/rag/sessions')).status,401);
  const form=new FormData();form.append('file',new Blob(['Zephyr delivery costs 7 JOD.']),'policy.txt');
  const up=await fetch(base+'/features/rag/documents',{method:'POST',headers,body:form});const upload=await up.json();assert.equal(up.status,201,JSON.stringify(upload));
  const documentId=upload.data.document_id;
  const corrupt=new FormData();corrupt.append('file',new Blob(['%PDF-not-valid']),'broken.pdf');
  assert.equal((await fetch(base+'/features/rag/documents',{method:'POST',headers,body:corrupt})).status,400);
  const query=async(requestId,sessionId)=>{
   const params=new URLSearchParams({query_text:'What does Zephyr delivery cost?',top_k:'5',request_id:requestId});if(sessionId)params.set('session_id',sessionId);
   const r=await fetch(base+'/features/rag/query?'+params,{method:'POST',headers});return {status:r.status,body:await r.json()};
  };
  const id=randomUUID(),first=await query(id);assert.equal(first.status,200,JSON.stringify(first));const data=first.body.data;
  assert.equal(data.sources[0].document,'policy.txt');assert.equal(data.sources[0].document_id,documentId);
  const chunkId=data.sources[0].chunk_id;
  assert.equal((await fetch(base+'/features/rag/chunks/'+chunkId,{headers})).status,200);
  assert.equal((await fetch(base+'/features/rag/chunks/'+chunkId,{headers:other})).status,404);
  assert.equal((await fetch(base+'/features/rag/chunks/not-a-uuid',{headers})).status,404);
  const sessions=await (await fetch(base+'/features/rag/sessions',{headers})).json();assert.equal(sessions.data.sessions.length,1);
  const freshHeaders=await login(a); // A new client/login can restore the persisted conversation.
  const restored=await (await fetch(base+'/features/rag/sessions/'+data.session_id,{headers:freshHeaders})).json();assert.equal(restored.data.turns[0].response.answer,data.answer);
  assert.equal((await fetch(base+'/features/rag/sessions/'+data.session_id,{headers:other})).status,404);
  assert.equal((await query(randomUUID(),data.session_id)).status,200);assert.equal(calls,2);
  assert.equal((await query(id)).status,200);assert.equal(calls,2); // Replay works with zero remaining allowance.
  assert.equal((await query(randomUUID())).status,402);assert.equal(calls,2);
  assert.equal((await fetch(base+`/features/rag/documents/${documentId}/reindex`,{method:'POST',headers})).status,200);
  assert.equal((await fetch(base+`/features/rag/documents/${documentId}/reindex`,{method:'POST',headers:other})).status,404);
  const filtered=await (await fetch(base+'/features/rag/documents?search=POLICY&sort=oldest',{headers})).json();assert.equal(filtered.data.documents[0].search_state,'ready');
  assert.equal((await fetch(base+'/features/rag/documents/'+documentId,{method:'DELETE',headers})).status,200);
  const invalidated=await (await fetch(base+'/features/rag/sessions/'+data.session_id,{headers})).json();assert.equal(invalidated.data.turns[0].response,null);
  for(let n=1;n<=12;n++) {
   const name=`Market_Brief_${String(n).padStart(2,'0')}.pdf`;
   const bytes=await readFile(new URL('./fixtures/market-pdfs/'+name,import.meta.url));
   const form=new FormData();form.append('file',new Blob([bytes],{type:'application/pdf'}),name);
   const response=await fetch(base+'/features/rag/documents',{method:'POST',headers,body:form});
   assert.equal(response.status,201,`${name}: ${JSON.stringify(await response.json())}`);
  }
  const pdfs=[];
  for(let page=1;page<=4;page++) {
   const result=await (await fetch(base+'/features/rag/documents?type=application%2Fpdf&page='+page,{headers})).json();
   assert.equal(result.data.pagination.total,12);
   pdfs.push(...result.data.documents);
  }
  assert.equal(pdfs.length,12);
  assert.ok(pdfs.every(doc=>doc.search_state==='ready'));
  console.log('PASS all 12 supplied market PDFs through authenticated multipart upload and restricted-role indexing');
  const beforeUsage=await f.db.query('SELECT id,current_usage FROM subscription_usage ORDER BY id');
  await mock.module('pdfjs-dist/legacy/build/pdf.mjs',{namedExports:{getDocument:()=>{throw new Error('PDF worker unavailable (regression fixture)');}}});
  const unavailableForm=new FormData();unavailableForm.append('file',new Blob([await readFile(new URL('./fixtures/market-pdfs/Market_Brief_01.pdf',import.meta.url))]),'valid.pdf');
  const unavailable=await fetch(base+'/features/rag/documents',{method:'POST',headers,body:unavailableForm});
  assert.equal(unavailable.status,503);
  assert.equal((await unavailable.json()).error.details.reason,'DOCUMENT_PROCESSING_UNAVAILABLE');
  assert.deepEqual((await f.db.query('SELECT id,current_usage FROM subscription_usage ORDER BY id')).rows,beforeUsage.rows);
  const unchanged=await (await fetch(base+'/features/rag/documents',{headers})).json();assert.equal(unchanged.data.pagination.total,12);
  console.log('PASS actual HTTP authorization, upload/index, private sessions, citation identity/detail, zero-budget idempotent replay, quota rejection, corruption rejection, reindex and deletion');
 }finally{mock.restoreAll();if(server)await new Promise(r=>server.close(r));if(prisma)await prisma.$disconnect();await f.close();}
});
