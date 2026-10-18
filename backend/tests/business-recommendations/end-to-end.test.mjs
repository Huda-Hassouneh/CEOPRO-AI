import test from 'node:test';import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';import {createServer} from 'node:net';import {resolve} from 'node:path';
import {randomBytes,randomUUID} from 'node:crypto';import express from 'express';import bcrypt from 'bcrypt';
import {isolatedDatabase,tenantFixture} from '../isolated/database.mjs';
const delay=ms=>new Promise(r=>setTimeout(r,ms));
test('real login -> Node -> Python API -> restricted PostgreSQL -> durable business findings, evidence and dismissal',async()=>{
 const f=await isolatedDatabase('ceopro_app',{maxConnections:10});let prisma,server,child,pythonLog='';
 const stopPython=async()=>{const running=child;child=null;if(!running||running.exitCode!==null)return;
  await new Promise(resolve=>{const timer=setTimeout(()=>running.kill('SIGKILL'),3000);running.once('exit',()=>{clearTimeout(timer);resolve();});running.kill('SIGTERM');});
 };

 try{
  await f.db.exec("SET TIME ZONE 'UTC'");const a=await tenantFixture(f.db),b=await tenantFixture(f.db),missing=await tenantFixture(f.db);
  await f.db.exec(`INSERT INTO features(feature_code,feature_name,feature_name_ar,feature_type) VALUES('business_recommendations','Business','Business','boolean'),('competitor_management','Competitors','Competitors','boolean') ON CONFLICT(feature_code) DO NOTHING;
    INSERT INTO features(feature_code,feature_name,feature_name_ar,feature_type,aggregation_type,reset_cycle) VALUES('tracked_competitors','Tracked','Tracked','limit','max','lifetime') ON CONFLICT(feature_code) DO NOTHING;`);
  for(const t of [a,b])await f.db.query(`INSERT INTO plan_features(plan_id,feature_id,limit_value) SELECT $1,feature_id,10 FROM features WHERE feature_code IN ('business_recommendations','competitor_management','tracked_competitors')`,[t.planId]);
  const password='BusinessFixturePass123!';for(const t of [a,b,missing])await f.db.query('UPDATE users SET password_hash=$1 WHERE user_id=$2',[await bcrypt.hash(password,10),t.userId]);
  const competitor=randomUUID(),mapping=randomUUID();
  await f.db.query(`INSERT INTO global_competitors(global_competitor_id,competitor_name) VALUES($1,'Business fixture competitor')`,[competitor]);
  await f.db.query('INSERT INTO tenant_competitors(tenant_id,global_competitor_id) VALUES($1,$2)',[a.tenantId,competitor]);
  await f.db.query(`INSERT INTO competitor_product_mappings(mapping_id,tenant_id,product_id,global_competitor_id,comparison_confirmed) VALUES($1,$2,$3,$4,true)`,[mapping,a.tenantId,a.productId,competitor]);
  await f.db.query(`INSERT INTO competitor_prices(tenant_id,mapping_id,scraped_price,currency,observed_at) VALUES($1,$2,8,'JOD',now()-interval '1 hour')`,[a.tenantId,mapping]);
  for(const [days,qty] of [[45,100],[10,30]])await f.db.query(`INSERT INTO transactions(tenant_id,product_id,quantity_sold,unit_price,total_price,original_currency,transaction_date) VALUES($1,$2,$3,10,$3*10,'JOD',now()-$4*interval '1 day')`,[a.tenantId,a.productId,qty,days]);
  const invoice=randomUUID();
  await f.db.query(`INSERT INTO invoices(invoice_id,tenant_id,invoice_number,currency,payment_status,issue_date) VALUES($1,$2,'overlapping-ledger','JOD','PAID',now()-interval '10 days')`,[invoice,a.tenantId]);
  await f.db.query(`INSERT INTO invoice_items(tenant_id,invoice_id,product_id,quantity,unit_price,total_price) VALUES($1,$2,$3,999,10,9990)`,[a.tenantId,invoice,a.productId]);
  // Target-day prediction, not a 30-day total; low daily demand supplies a third signal.
  await f.db.query(`INSERT INTO demand_forecasts(tenant_id,product_id,forecast_target_date,expected_demand,model_version) VALUES($1,$2,CURRENT_DATE+7,0.1,'isolated-target-day')`,[a.tenantId,a.productId]);
  process.env.DATABASE_URL=f.url;process.env.JWT_SECRET=randomBytes(32).toString('hex');await f.role('ceopro_app');({prisma}=await import('../../src/config/database.ts'));
  const reserve=createServer();await new Promise(r=>reserve.listen(0,'127.0.0.1',r));const port=reserve.address().port;await new Promise(r=>reserve.close(r));
  const python=process.env.KEEL_TEST_PYTHON||'python';
  child=spawn(python,['-m','uvicorn','src.ai.insights.app:app','--host','127.0.0.1','--port',String(port)],{cwd:resolve('../ai'),env:{...process.env,DATABASE_URL:f.url+'?sslmode=disable&gssencmode=disable&connect_timeout=5',APP_DB_PASSWORD:'isolated-fixture',APP_DB_POOL_MIN_SIZE:'1',APP_DB_POOL_MAX_SIZE:'1'},stdio:['ignore','pipe','pipe']});
  child.stdout.on('data',x=>{pythonLog=(pythonLog+x).slice(-20000);});child.stderr.on('data',x=>{pythonLog=(pythonLog+x).slice(-20000);});
  process.env.BUSINESS_INSIGHTS_API_URL=`http://127.0.0.1:${port}`;let ready=false;
  for(let n=0;n<200;n++){if(child.exitCode!==null)break;try{if((await fetch(process.env.BUSINESS_INSIGHTS_API_URL+'/health')).ok){ready=true;break;}}catch{}await delay(100);}
  assert.ok(ready,'Python insight API did not start. Set KEEL_TEST_PYTHON to an environment with requirements-insights.txt. '+pythonLog);
  const {default:auth}=await import('../../src/modules/auth/route/auth.route.ts');const {default:recommendations}=await import('../../src/modules/business-recommendations/route.ts');
  const app=express();app.use(express.json());app.use('/auth',auth);app.use('/features/business-recommendations',recommendations);
  server=await new Promise(r=>{const s=app.listen(0,'127.0.0.1',()=>r(s));});const base=`http://127.0.0.1:${server.address().port}`;
  const login=async t=>{const r=await fetch(base+'/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({email:`${t.userId}@example.test`,password})});const j=await r.json();assert.equal(r.status,200,JSON.stringify(j));return {Authorization:`Bearer ${j.session.accessToken}`};};
  const own=await login(a),other=await login(b),none=await login(missing);
  const refresh=async(headers,id=randomUUID())=>{const r=await fetch(base+'/features/business-recommendations/refresh',{method:'POST',headers:{...headers,'Content-Type':'application/json'},body:JSON.stringify({request_id:id})});return {status:r.status,body:await r.json()};};
  const list=async(headers,query='')=>{const r=await fetch(base+'/features/business-recommendations'+query,{headers});return {status:r.status,body:await r.json()};};
  assert.equal((await list({})).status,401);assert.equal((await refresh(none)).status,403);
  assert.equal((await fetch(process.env.BUSINESS_INSIGHTS_API_URL+'/business-recommendations',{headers:own})).status,401,'A customer JWT alone cannot bypass Node by calling Python directly');
  const request=randomUUID(),first=await refresh(own,request);if(first.status!==200)await delay(300);assert.equal(first.status,200,JSON.stringify(first.body)+'\n'+pythonLog);assert.equal(first.body.data.total,1);
  const feed=await list(own);assert.equal(feed.status,200);assert.equal(feed.body.data.recommendations.length,1);
  const rec=feed.body.data.recommendations[0];assert.equal(rec.priority,'high');assert.equal(rec.body.evidence.sales.source,'transactions');assert.equal(rec.body.evidence.sales.recent_units,30);assert.equal(rec.body.evidence.sales.prior_units,100);
  assert.equal(rec.body.evidence.sources.find(s=>s.table==='demand_forecasts').prediction_kind,'target_day');assert.ok(rec.body.message_i18n.ar);
  assert.deepEqual(await refresh(own,request),first);const second=await refresh(own);assert.equal(second.status,200,JSON.stringify(second.body));assert.equal(second.body.data.changed_count,0);
  assert.equal((await list(other)).body.data.total,0);
  assert.equal((await fetch(base+'/features/business-recommendations/'+rec.recommendation_id+'/evidence',{headers:other})).status,404);
  const change=state=>fetch(base+'/features/business-recommendations/'+rec.recommendation_id+'/state',{method:'PATCH',headers:{...own,'Content-Type':'application/json'},body:JSON.stringify({state})});
  assert.equal((await change('dismissed')).status,200);assert.equal((await list(own)).body.data.total,0);await refresh(own);assert.equal((await list(own,'?state=dismissed')).body.data.total,1);
  assert.equal((await change('active')).status,200);assert.equal((await list(await login(a))).body.data.total,1);
  const admin=async fn=>{await f.role('postgres');try{return await fn();}finally{await f.role('ceopro_app');}};
  assert.equal((await admin(()=>f.db.query(`SELECT count(*)::int AS n FROM tenant_notification_outbox WHERE tenant_id=$1 AND event_type='BUSINESS_RECOMMENDATION_READY'`,[a.tenantId]))).rows[0].n,1);
  // No engine response may wipe saved findings on an outage.
  await stopPython();
  assert.equal((await refresh(own)).status,503);assert.equal((await list(own)).body.data.total,1);
  console.log('PASS actual Node/Python HTTP, canonical imported sales, single-day forecast, stable refresh, evidence, notification dedupe, cross-tenant denial, persistence, dismissal and outage retention');
 }finally{await stopPython();if(server)await new Promise(r=>server.close(r));if(prisma)await prisma.$disconnect();await f.close();}
});
