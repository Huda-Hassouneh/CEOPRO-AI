import test,{mock} from 'node:test';
import assert from 'node:assert/strict';
import {randomUUID} from 'node:crypto';
import {isolatedDatabase,tenantFixture,planFixture} from '../isolated/database.mjs';

test('pricing generation, quota reservations, evidence and retries under restricted ceopro_app',async()=>{
 const f=await isolatedDatabase('ceopro_app');let prisma;
 try{
  await f.db.exec("SET TIME ZONE 'UTC'");
  const a=await tenantFixture(f.db),b=await tenantFixture(f.db),limited=await tenantFixture(f.db);
  await f.db.exec(`INSERT INTO features(feature_code,feature_name,feature_name_ar,feature_type,aggregation_type,reset_cycle) VALUES('ai_pricing','Pricing','Pricing','limit','sum','billing_period') ON CONFLICT(feature_code) DO NOTHING`);
  await f.db.exec(`INSERT INTO features(feature_code,feature_name,feature_name_ar,feature_type) VALUES('competitor_management','Competitors','Competitors','boolean') ON CONFLICT(feature_code) DO NOTHING;
    INSERT INTO features(feature_code,feature_name,feature_name_ar,feature_type,aggregation_type,reset_cycle) VALUES('tracked_competitors','Tracked','Tracked','limit','max','lifetime') ON CONFLICT(feature_code) DO NOTHING`);
  for(const t of [a,b,limited])await f.db.query(`INSERT INTO plan_features(plan_id,feature_id,limit_value) SELECT $1,feature_id,20 FROM features WHERE feature_code IN ('competitor_management','tracked_competitors')`,[t.planId]);
  for(const [t,limit] of [[a,100],[limited,1]])await f.db.query(`INSERT INTO plan_features(plan_id,feature_id,limit_value) SELECT $1,feature_id,$2 FROM features WHERE feature_code='ai_pricing'`,[t.planId,limit]);
  const mapping=async(t,name,currency,price)=>{
   const competitorId=randomUUID(),mappingId=randomUUID(),priceId=randomUUID();
   await f.db.query(`INSERT INTO global_competitors(global_competitor_id,competitor_name,visibility,added_by_tenant_id) VALUES($1,$2,'PRIVATE',$3)`,[competitorId,name,t.tenantId]);
   await f.db.query(`INSERT INTO tenant_competitors(tenant_id,global_competitor_id,is_tracked) VALUES($1,$2,true)`,[t.tenantId,competitorId]);
   await f.db.query(`INSERT INTO competitor_product_mappings(mapping_id,tenant_id,global_competitor_id,product_id,comparison_confirmed) VALUES($1,$2,$3,$4,true)`,[mappingId,t.tenantId,competitorId,t.productId]);
   await f.db.query(`INSERT INTO competitor_prices(competitor_price_id,tenant_id,mapping_id,scraped_price,currency,observed_at) VALUES($1,$2,$3,$4,$5,now()-interval '1 minute')`,[priceId,t.tenantId,mappingId,price,currency]);
   return {competitorId,mappingId,priceId};
  };
  const local=await mapping(a,'Local market','JOD',8),foreign=await mapping(a,'USD reference','USD',10);
  await mapping(limited,'Limited market','JOD',8);await mapping(b,'Other tenant market','JOD',1000);
  await f.db.exec(`INSERT INTO currency_rates(from_currency,to_currency,exchange_rate,last_fetched,source) VALUES('USD','JOD',0.71,now(),'fixture-bank')`);
  for(let n=1;n<=12;n++)await f.db.query(`INSERT INTO competitor_prices(tenant_id,mapping_id,scraped_price,currency,observed_at) VALUES($1,$2,1,'JOD',now()-interval '1 day'-$3*interval '1 minute')`,[a.tenantId,local.mappingId,n]);
  process.env.DATABASE_URL=f.url;await f.role('ceopro_app');({prisma}=await import('../../src/config/database.ts'));
  let calls=0,mode='ok',release,entered;
  await mock.module('../../src/modules/pricing/client/pricing.client.ts',{namedExports:{readPricingExplanation:()=> 'Provider explanation (audit only)',isPricingClientError:()=>false,
   requestPricingRecommendation:async input=>{
    calls++;assert.ok(!input.competitorPrices.some(p=>p.price===1));
    if(mode==='throw')throw new Error('fixture provider timeout');
    if(mode==='pending'){entered();await new Promise(r=>{release=r;});}
    if(mode==='unknown')return {result:{status:'UNKNOWN'},persisted_records:[]};
    return {result:{status:'OK',action:'lower',current_price:mode==='wrong'?999:input.product.current_price,suggested_price:mode==='zero'?0:8,
     matched_competitor_count:input.competitorPrices.filter(p=>p.currency===input.product.currency).length,confidence_score:0.35,guardrail_clamped:false,margin_guardrail_clamped:null},persisted_records:[]};
   }}});
  const service=await import('../../src/modules/pricing/service/pricing.service.ts');
  const repo=await import('../../src/modules/pricing/repo/pricing.repo.ts');
  const debugPoints=await repo.getEligibleMarketPrices({...a,observedAfter:new Date(Date.now()-30*86400000),observedBefore:new Date()});
  assert.equal(debugPoints.length,2,JSON.stringify(debugPoints));
  const requests=await import('../../src/modules/pricing/repo/pricing-request.repo.ts');
  const ask=(t,requestId=randomUUID())=>service.getPricingRecommendation({tenantId:t.tenantId,userId:t.userId,productId:t.productId,requestId});
  const admin=async fn=>{await f.role('postgres');try{return await fn();}finally{await f.role('ceopro_app');}};
  const usage=t=>admin(async()=>Number((await f.db.query(`SELECT coalesce(sum(u.current_usage),0)::int AS n FROM subscription_usage u JOIN subscriptions s ON s.id=u.subscription_id JOIN features fe ON fe.feature_id=u.feature_id WHERE s.tenant_id=$1 AND fe.feature_code='ai_pricing'`,[t.tenantId])).rows[0].n));
  const countEvidence=()=>admin(async()=>Number((await f.db.query(`SELECT count(*)::int AS n FROM evidence_records WHERE tenant_id=$1 AND source_module='pricing'`,[a.tenantId])).rows[0].n));
  const id=randomUUID(),first=await ask(a,id);
  assert.equal(first.market_avg,8);assert.equal(first.matched_competitor_count,1);assert.equal(first.sources[0].competitor_price_id,local.priceId);
  assert.equal(first.reference_sources[0].original_price,10);assert.equal(first.reference_sources[0].converted_price,7.1);
  assert.equal(first.suggested_price,8.5);assert.equal(first.guardrail_clamped,true);assert.equal(first.charged,true);assert.equal(await usage(a),1);
  assert.deepEqual(await ask(a,id),first);assert.equal(calls,1);assert.equal(await countEvidence(),1);
  assert.equal((await service.getPricingHistory(a)).recommendations[0].evidence_id,first.evidence_id);
  const evidence=await admin(async()=>(await f.db.query(`SELECT metric_value_json,source_record_ids FROM evidence_records WHERE evidence_id=$1`,[first.evidence_id])).rows[0]);
  assert.deepEqual(evidence.source_record_ids.competitor_price_ids,[local.priceId]);assert.deepEqual(evidence.source_record_ids.reference_competitor_price_ids,[foreign.priceId]);
  assert.equal(evidence.metric_value_json.reference_sources[0].conversion.rate,0.71);
  await assert.rejects(()=>ask({...a,productId:b.productId}),e=>e.code==='PRODUCT_NOT_FOUND');
  await assert.rejects(()=>ask(b),e=>e.name==='FeatureUsageUnavailableError');assert.equal(calls,1);
  const product2=randomUUID();await admin(()=>f.db.query(`INSERT INTO products(product_id,tenant_id,product_name,current_price,currency) VALUES($1,$2,'{"en":"Second"}',10,'JOD')`,[product2,a.tenantId]));
  await assert.rejects(()=>ask({...a,productId:product2},id),e=>e.code==='REQUEST_CONFLICT');
  for(const failure of ['throw','wrong','zero']){mode=failure;const before=await usage(a);await assert.rejects(()=>ask(a));assert.equal(await usage(a),before);}
  mode='unknown';const beforeUnknown=await usage(a),unknown=await ask(a);
  assert.equal(unknown.status,'UNKNOWN');assert.equal(unknown.charged,false);assert.equal(unknown.outcome_id,null);assert.equal(await usage(a),beforeUnknown);mode='ok';
  await admin(()=>f.db.exec(`CREATE FUNCTION fixture_fail_pricing() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NEW.status='completed' THEN RAISE EXCEPTION 'fixture pricing persistence failure'; END IF; RETURN NEW; END $$; CREATE TRIGGER fixture_fail_pricing BEFORE UPDATE ON pricing_requests FOR EACH ROW EXECUTE FUNCTION fixture_fail_pricing();`));
  const beforeFailure=await usage(a),evidenceBefore=await countEvidence();await assert.rejects(()=>ask(a),/fixture pricing persistence failure/);
  assert.equal(await usage(a),beforeFailure);assert.equal(await countEvidence(),evidenceBefore);
  await admin(()=>f.db.exec('DROP TRIGGER fixture_fail_pricing ON pricing_requests; DROP FUNCTION fixture_fail_pricing();'));
  for(const [field,value,restore] of [['comparison_confirmed',false,true],['is_active',false,true],['tracking_paused',true,false]]){
   await admin(()=>f.db.query(`UPDATE competitor_product_mappings SET ${field}=$1 WHERE mapping_id=$2`,[value,local.mappingId]));
   const before=calls;assert.equal((await ask(a)).status,'UNKNOWN');assert.equal(calls,before);
   await admin(()=>f.db.query(`UPDATE competitor_product_mappings SET ${field}=$1 WHERE mapping_id=$2`,[restore,local.mappingId]));
  }
  // Source decisions and exactness on the newest row are authoritative.
  for(const patch of ["source_status='RESTRICTED'","is_exact_data=false","scraped_price=0","observed_at=now()+interval '1 day'","observed_at=now()-interval '31 days'"]){
   await admin(()=>f.db.query(`UPDATE competitor_prices SET ${patch} WHERE competitor_price_id=$1`,[local.priceId]));
   // For a stale edited row, newer eligible historical rows are legitimately
   // selected. Remove them first for a clean missing/stale fixture.
   if(patch.includes('31 days'))await admin(()=>f.db.query('DELETE FROM competitor_prices WHERE mapping_id=$1 AND competitor_price_id<>$2',[local.mappingId,local.priceId]));
   const before=calls;assert.equal((await ask(a)).status,'UNKNOWN');assert.equal(calls,before);
   await admin(()=>f.db.query(`UPDATE competitor_prices SET source_status='ALLOWED',is_exact_data=true,scraped_price=8,observed_at=now()-interval '1 minute' WHERE competitor_price_id=$1`,[local.priceId]));
  }
  const blocked=randomUUID();await admin(()=>f.db.query(`INSERT INTO competitor_prices(competitor_price_id,tenant_id,mapping_id,scraped_price,currency,is_available,observed_at) VALUES($1,$2,$3,7,'JOD',false,now())`,[blocked,a.tenantId,local.mappingId]));
  assert.equal((await service.getPricingHistory(a)).recommendations.find(r=>r.request_id===id).is_stale,true);
  let beforeCalls=calls;const crossOnly=await ask(a);assert.equal(crossOnly.reason,'CROSS_CURRENCY_ONLY');assert.equal(crossOnly.market_avg,null);assert.equal(calls,beforeCalls);
  await admin(()=>f.db.exec(`UPDATE currency_rates SET last_fetched=now()-interval '8 days'`));
  assert.equal((await ask(a)).reason,'NO_VERIFIED_FX');assert.equal(calls,beforeCalls);
  await admin(async()=>{await f.db.query('DELETE FROM competitor_prices WHERE competitor_price_id=$1',[blocked]);await f.db.exec('UPDATE currency_rates SET last_fetched=now()');});
  await admin(()=>f.db.query(`UPDATE products SET cost_price=12,version=version+1 WHERE product_id=$1`,[a.productId]));
  const override=await ask(a);assert.equal(override.action,'raise');assert.equal(override.suggested_price,13.2);assert.equal(override.movement_cap_overridden,true);
  assert.equal((await service.getPricingHistory(a)).recommendations.find(r=>r.request_id===id).is_stale,true);
  let waiting=new Promise(r=>{entered=r;});mode='pending';let pending=ask(a);await waiting;
  await admin(()=>f.db.query('UPDATE products SET current_price=11 WHERE product_id=$1',[a.productId]));release();await assert.rejects(()=>pending,e=>e.code==='SOURCE_CHANGED');mode='ok';
  waiting=new Promise(r=>{entered=r;});mode='pending';const lastId=randomUUID();pending=ask(limited,lastId);await waiting;
  beforeCalls=calls;await assert.rejects(()=>ask(limited,lastId),e=>e.code==='REQUEST_PENDING');await assert.rejects(()=>ask(limited),e=>e.code==='REQUEST_PENDING');assert.equal(calls,beforeCalls);
  release();const last=await pending;assert.equal(last.charged,true);assert.equal(await usage(limited),1);
  assert.deepEqual(await ask(limited,lastId),last);assert.equal(calls,beforeCalls);
  await assert.rejects(()=>ask(limited),e=>e.name==='FeatureUsageCapacityError');assert.equal(calls,beforeCalls);
  await admin(()=>f.db.query(`UPDATE subscriptions SET current_period_start=now(),current_period_end=now()+interval '30 days' WHERE id=$1`,[limited.subscriptionId]));
  const crashed=randomUUID();await requests.beginPricingRequest(limited,crashed,limited.productId);
  await admin(()=>f.db.query(`UPDATE pricing_requests SET expires_at=now()-interval '1 second' WHERE request_id=$1`,[crashed]));
  await requests.recoverPricingRequests(limited);await requests.recoverPricingRequests(limited);assert.equal(await usage(limited),1);
  await assert.rejects(()=>requests.finishPricingRequest(limited,crashed,{productId:limited.productId},last),e=>e.code==='REQUEST_EXPIRED');
  const holdId=randomUUID();await requests.beginPricingRequest(a,holdId,a.productId);
  const replacement=await admin(async()=>{await f.db.query("UPDATE subscriptions SET status='canceled' WHERE id=$1",[a.subscriptionId]);return planFixture(f.db,a.tenantId);});
  await requests.failPricingRequest(a,holdId,'fixture');await requests.failPricingRequest(a,holdId,'fixture');
  assert.equal((await admin(()=>f.db.query('SELECT * FROM subscription_usage WHERE subscription_id=$1',[replacement.subscriptionId]))).rows.length,0);
  const foreignUsage=(await admin(()=>f.db.query('SELECT usage_record_id FROM pricing_requests WHERE tenant_id=$1 LIMIT 1',[limited.tenantId]))).rows[0].usage_record_id;
  await assert.rejects(()=>prisma.$transaction(async tx=>{
   await tx.$executeRaw`SELECT set_config('app.current_tenant_id',${a.tenantId},true),set_config('app.current_user_id',${a.userId},true)`;
   await tx.$executeRaw`INSERT INTO pricing_requests(tenant_id,user_id,request_id,product_id,usage_record_id,status) VALUES(${a.tenantId}::uuid,${a.userId}::uuid,${randomUUID()}::uuid,${a.productId}::uuid,${foreignUsage}::uuid,'pending')`;
  }),/row-level security/);
  await prisma.$transaction(async tx=>{await tx.$executeRaw`SELECT set_config('app.current_tenant_id',${b.tenantId},true),set_config('app.current_user_id',${b.userId},true)`;
   assert.equal((await tx.$queryRaw`SELECT * FROM pricing_requests WHERE tenant_id=${a.tenantId}::uuid`).length,0);
  });
  console.log('PASS restricted-role inputs, reference-only FX, guardrails, exact evidence, replay, UNKNOWN/error refunds, rollback, pending contention, period reset, expiry, original-allocation refund and RLS');
 }finally{mock.restoreAll();if(prisma)await prisma.$disconnect();await f.close();}
});
