import test from 'node:test';
import assert from 'node:assert/strict';
import express from 'express';
import bcrypt from 'bcrypt';
import {randomBytes} from 'node:crypto';
import {isolatedDatabase,tenantFixture} from '../isolated/database.mjs';
test('real authenticated HTTP upload/list/delete reclaims storage without mock authentication',async()=>{
 const f=await isolatedDatabase('ceopro_app');let prisma,server;
 try{
  const t=await tenantFixture(f.db);
  const password='IsolatedStoragePass123!';
  await f.db.query('UPDATE users SET password_hash=$1 WHERE user_id=$2',[await bcrypt.hash(password,10),t.userId]);
  process.env.DATABASE_URL=f.url;process.env.JWT_SECRET=randomBytes(32).toString('hex');await f.role('ceopro_app');
  ({prisma}=await import('../../src/config/database.ts'));
  const {default:auth}=await import('../../src/modules/auth/route/auth.route.ts');
  const {default:rag}=await import('../../src/modules/rag/route/rag.route.ts');
  const app=express();app.use(express.json());app.use('/auth',auth);app.use('/features/rag',rag);
  app.use((error,_req,res,_next)=>res.status(500).json({message:error.message}));
  server=await new Promise(resolve=>{const s=app.listen(0,'127.0.0.1',()=>resolve(s));});
  const base=`http://127.0.0.1:${server.address().port}`;
  const login=await fetch(base+'/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({email:`${t.userId}@example.test`,password})});
  const body=await login.json();assert.equal(login.status,200,JSON.stringify(body));
  const headers={Authorization:`Bearer ${body.session.accessToken}`};
  assert.equal((await fetch(base+'/features/rag/documents')).status,401);
  const form=new FormData();form.append('file',new Blob(['Known source text.']), 'known.md');
  const response=await fetch(base+'/features/rag/documents',{method:'POST',headers,body:form});const upload=await response.json();
  assert.equal(response.status,201,JSON.stringify(upload));assert.equal(upload.data.processed_status,'Stored');
  const list=await (await fetch(base+'/features/rag/documents',{headers})).json();
  assert.equal(list.data.documents.length,1);assert.equal(list.data.storage.usedBytes,18);assert.equal(list.data.documents[0].storage_owned_by_node,true);
  const deleted=await fetch(base+`/features/rag/documents/${upload.data.document_id}`,{method:'DELETE',headers});assert.equal(deleted.status,200,await deleted.text());
  const empty=await (await fetch(base+'/features/rag/documents',{headers})).json();assert.equal(empty.data.storage.usedBytes,0);assert.equal(empty.data.documents.length,0);
  assert.equal((await fetch(base+`/features/rag/documents/${upload.data.document_id}`,{method:'DELETE',headers})).status,404);
  console.log('PASS real login/JWT/session validation + multipart upload/list/delete; unauthorized denied; repeated delete returns 404');
 }finally{if(server)await new Promise(r=>server.close(r));if(prisma)await prisma.$disconnect();await f.close();}
});
