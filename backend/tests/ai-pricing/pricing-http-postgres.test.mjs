import test,{mock} from 'node:test';import assert from 'node:assert/strict';
import express from 'express';import bcrypt from 'bcrypt';import {randomBytes,randomUUID} from 'node:crypto';
import {isolatedDatabase,tenantFixture} from '../isolated/database.mjs';

test('authenticated pricing API: quota-safe replay, history, tenant access, disabled allocation and suspended membership',async()=>{
 const f=await isolatedDatabase('ceopro_app');let prisma,server;
 try{
  await f.db.exec("SET TIME ZONE 'UTC'");
  const a=await tenantFixture(f.db),b=await tenantFixture(f.db),excluded=await tenantFixture(f.db),password='PricingHttpFixture123!';
  await f.db.exec(`INSERT INTO features(feature_code,feature_name,feature_name_ar,feature_type,aggregation_type,reset_cycle) VALUES('ai_pricing','Pricing','Pricing','limit','sum','billing_period') ON CONFLICT(feature_code) DO NOTHING;
   INSERT INTO features(feature_code,feature_name,feature_name_ar,feature_type) VALUES('competitor_management','Competitors','Competitors','boolean') ON CONFLICT(feature_code) DO NOTHING;
   INSERT INTO features(feature_code,feature_name,feature_name_ar,feature_type,aggregation_type,reset_cycle) VALUES('tracked_competitors','Tracked','Tracked','limit','max','lifetime') ON CONFLICT(feature_code) DO NOTHING`);
  for(const t of [a,b])await f.db.query(`INSERT INTO plan_features(plan_id,feature_id,limit_value) SELECT $1,feature_id,1 FROM features WHERE feature_code IN ('ai_pricing','competitor_management','tracked_competitors')`,[t.planId]);
  for(const t of [a,b,excluded])await f.db.query('UPDATE users SET password_hash=$1 WHERE user_id=$2',[await bcrypt.hash(password,10),t.userId]);
  const competitor=randomUUID(),mapping=randomUUID();
  await f.db.query(`INSERT INTO global_competitors(global_competitor_id,competitor_name) VALUES($1,'Fixture market')`,[competitor]);
  await f.db.query(`INSERT INTO tenant_competitors(tenant_id,global_competitor_id) VALUES($1,$2)`,[a.tenantId,competitor]);
  await f.db.query(`INSERT INTO competitor_product_mappings(mapping_id,tenant_id,global_competitor_id,product_id,comparison_confirmed) VALUES($1,$2,$3,$4,true)`,[mapping,a.tenantId,competitor,a.productId]);
  await f.db.query(`INSERT INTO competitor_prices(tenant_id,mapping_id,scraped_price,currency,observed_at) VALUES($1,$2,8,'JOD',now()-interval '1 minute')`,[a.tenantId,mapping]);
  process.env.DATABASE_URL=f.url;process.env.JWT_SECRET=randomBytes(32).toString('hex');await f.role('ceopro_app');({prisma}=await import('../../src/config/database.ts'));
  let calls=0;
  await mock.module('../../src/modules/pricing/client/pricing.client.ts',{namedExports:{isPricingClientError:()=>false,readPricingExplanation:()=>null,
   requestPricingRecommendation:async input=>{calls++;return {result:{status:'OK',action:'lower',current_price:input.product.current_price,suggested_price:8.5,matched_competitor_count:1,confidence_score:0.35,guardrail_clamped:true,margin_guardrail_clamped:null},persisted_records:[]};}}});
  const {default:auth}=await import('../../src/modules/auth/route/auth.route.ts');const {default:pricing}=await import('../../src/modules/pricing/route/pricing.route.ts');
  const app=express();app.use(express.json());app.use('/auth',auth);app.use('/features/pricing',pricing);app.use((e,_req,res,_next)=>res.status(500).json({message:e.message}));
  server=await new Promise(resolve=>{const s=app.listen(0,'127.0.0.1',()=>resolve(s));});const base=`http://127.0.0.1:${server.address().port}`;
  const login=async t=>{const r=await fetch(base+'/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({email:`${t.userId}@example.test`,password})});const body=await r.json();assert.equal(r.status,200,JSON.stringify(body));return {Authorization:`Bearer ${body.session.accessToken}`};};
  const own=await login(a),other=await login(b),none=await login(excluded);
  const post=async(headers,product=a.productId,id=randomUUID())=>{const r=await fetch(base+'/features/pricing/recommend?'+new URLSearchParams({product_id:product,request_id:id}),{method:'POST',headers});return {status:r.status,body:await r.json()};};
  const history=(headers,product=a.productId)=>fetch(base+'/features/pricing/history?product_id='+product,{headers});
  assert.equal((await post({})).status,401);assert.equal((await post(none,excluded.productId)).status,403);
  assert.equal((await post(other)).status,404);assert.equal((await post(own,'bad')).status,400);
  assert.equal((await post(own,a.productId,'bad')).status,400);assert.equal(calls,0);
  const id=randomUUID(),first=await post(own,a.productId,id);assert.equal(first.status,200,JSON.stringify(first.body));assert.equal(first.body.data.charged,true);assert.equal(calls,1);
  assert.deepEqual(await post(own,a.productId,id),first);assert.equal(calls,1);
  assert.equal((await post(own)).status,402);assert.equal(calls,1);
  const fresh=await login(a),saved=await (await history(fresh)).json();assert.equal(saved.data.recommendations[0].evidence_id,first.body.data.evidence_id);
  assert.equal(saved.data.recommendations[0].sources.length,1);assert.equal((await history(other)).status,404);assert.equal((await history(none,excluded.productId)).status,403);
  const admin=async fn=>{await f.role('postgres');try{return await fn();}finally{await f.role('ceopro_app');}};
  await admin(()=>f.db.query(`UPDATE tenant_users SET platform_status='suspended' WHERE tenant_id=$1 AND user_id=$2`,[a.tenantId,a.userId]));
  assert.equal((await history(own)).status,403);assert.equal((await post(own,a.productId,id)).status,403);assert.equal(calls,1);
  await admin(()=>f.db.query(`UPDATE tenant_users SET platform_status='active' WHERE tenant_id=$1 AND user_id=$2`,[a.tenantId,a.userId]));
  await admin(()=>f.db.query(`DELETE FROM plan_features WHERE plan_id=$1 AND feature_id=(SELECT feature_id FROM features WHERE feature_code='ai_pricing')`,[a.planId]));
  assert.equal((await history(own)).status,403);assert.equal((await post(own,a.productId,id)).status,403);assert.equal(calls,1);
  console.log('PASS real login, UUID validation, restricted-role generation, zero-credit replay, persisted history after fresh login, missing entitlement, suspension and cross-tenant denial');
 }finally{mock.restoreAll();if(server)await new Promise(r=>server.close(r));if(prisma)await prisma.$disconnect();await f.close();}
});
