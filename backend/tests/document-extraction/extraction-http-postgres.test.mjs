import test from 'node:test';
import assert from 'node:assert/strict';
import express from 'express';
import bcrypt from 'bcrypt';
import {randomBytes} from 'node:crypto';
import {isolatedDatabase,tenantFixture} from '../isolated/database.mjs';
test('real HTTP sales upload queues all rows and restricted worker promotes them idempotently',async()=>{
 const f=await isolatedDatabase('ceopro_app');let prisma,server,worker;
 try{
  const t=await tenantFixture(f.db);
  const password='IsolatedStoragePass123!';
  await f.db.query('UPDATE users SET password_hash=$1 WHERE user_id=$2',[await bcrypt.hash(password,10),t.userId]);
  process.env.DATABASE_URL=f.url;process.env.JWT_SECRET=randomBytes(32).toString('hex');await f.role('ceopro_app');
  ({prisma}=await import('../../src/config/database.ts'));
  const {default:auth}=await import('../../src/modules/auth/route/auth.route.ts');
  const {default:rag}=await import('../../src/modules/dataconnection/route/dataconnection.route.ts');
  const app=express();app.use(express.json());app.use('/auth',auth);app.use('/data-connection',rag);
  app.use((error,_req,res,_next)=>res.status(500).json({message:error.message}));
  server=await new Promise(resolve=>{const s=app.listen(0,'127.0.0.1',()=>resolve(s));});
  const base=`http://127.0.0.1:${server.address().port}`;
  const login=await fetch(base+'/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({email:`${t.userId}@example.test`,password})});
  const body=await login.json();assert.equal(login.status,200,JSON.stringify(body));
  const headers={Authorization:`Bearer ${body.session.accessToken}`};
  const csv='product_name,quantity,unit_price,currency,transaction_date,sale_id,source_system\nTea,2,10,JOD,2026-10-01,line-1,pos\nTea,2,10,JOD,2026-10-01,line-1,pos\n';
  async function upload(){const form=new FormData();form.append('file',new Blob([csv]),'sales.csv');
    const r=await fetch(base+'/data-connection',{method:'POST',headers,body:form});const result=await r.json();assert.equal(r.status,200,JSON.stringify(result));return result.data;}
  const queued=await upload();assert(queued.job_id);assert.equal(queued.source_rows_total,2);assert.equal(queued.import_complete,true);
  const duplicate=await upload();assert.equal(duplicate.job_id,queued.job_id);
  await new Promise(r=>server.close(r));server=null;await prisma.$disconnect();prisma=null;
  await f.socket.stop();await f.socket.start();
  process.env.INGESTION_WORKER_DATABASE_URL=`postgresql://ceopro_ingestion_worker@${f.socket.getServerConn()}/postgres`;await f.role('ceopro_ingestion_worker');
  ({ingestionWorkerPrisma:worker}=await import('../../src/config/ingestion-worker-database.ts'));
  const {ingestionWorkerRepo}=await import('../../src/modules/dataconnection/repo/ingestion-worker.repo.ts');
  const jobs=await ingestionWorkerRepo.claimPendingJobs(1);assert.equal(jobs.length,1);
  const result=await ingestionWorkerRepo.processClaimedJob(jobs[0]);assert.equal(result.committed,2);
  await f.role('postgres');assert.equal((await f.db.query('SELECT count(*)::int AS n FROM transactions WHERE tenant_id=$1',[t.tenantId])).rows[0].n,1);
  assert.equal((await f.db.query('SELECT job_status FROM ingestion_jobs WHERE job_id=$1',[queued.job_id])).rows[0].job_status,'COMPLETED');
  console.log('PASS actual authenticated multipart CSV -> complete staging -> worker claim -> product reuse / one transaction -> completed job; exact upload retry reused');

 }finally{if(server)await new Promise(r=>server.close(r));if(prisma)await prisma.$disconnect();if(worker)await worker.$disconnect();await f.close();}
});
