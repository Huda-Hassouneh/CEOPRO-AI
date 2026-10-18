import {COMPETITOR_AI_ACTIONS_ENABLED} from '../service/competitor-capabilities.js';
import type {Prisma} from '../../../generated/prisma/client.js';
import {publishMarketEvent} from '../client/market-redis.client.js';
import {collectionCostDecision} from '../client/market-cost-guard.client.js';
import {requestCollection} from './market-tracking.requests.js';
type Database={ $transaction: <T>(fn:(tx:Prisma.TransactionClient)=>Promise<T>,options:{maxWait:number;timeout:number})=>Promise<T> };
type Event={event_id:string;tenant_id:string;source_id:string|null;kind:'DISCOVERY'|'COLLECTION';competitor_id:string|null;attempts:number;dedupe_key:string};
const opts={maxWait:10000,timeout:30000};
export async function scheduleMarketSources(db:Database) {
 if(!COMPETITOR_AI_ACTIONS_ENABLED) return 0;
 return db.$transaction(async tx=>{
  const sources=await tx.$queryRaw<Array<{tenant_id:string;source_id:string;minutes:number}>>`
   SELECT ds.tenant_id,ds.source_id,(pf.metadata->'configuration'->>'monitoringFrequencyMinutes')::int AS minutes
   FROM data_sources ds
   JOIN companies c ON c.tenant_id=ds.tenant_id AND c.deleted_at IS NULL AND c.platform_status='active'
   JOIN LATERAL(SELECT s.plan_id FROM subscriptions s WHERE s.tenant_id=ds.tenant_id AND s.status IN ('active','trialing') ORDER BY s.updated_at DESC,s.created_at DESC LIMIT 1) s ON true
   JOIN plan_features pf ON pf.plan_id=s.plan_id JOIN features f ON f.feature_id=pf.feature_id AND f.feature_code='competitor_management'
   WHERE ds.source_type IN ('website','WEB_SCRAPE') AND ds.is_active AND ds.policy_status='ALLOWED'
    AND ds.collector_key IS NOT NULL AND ds.collector_key NOT IN ('db_connector','api_connector')
    AND ds.approval_reference IS NOT NULL AND ds.approved_by IS NOT NULL AND ds.approved_at IS NOT NULL AND ds.privacy_reviewed_at IS NOT NULL
    AND (pf.metadata->'configuration'->>'monitoringFrequencyMinutes') ~ '^[0-9]{1,6}$'
    AND CASE WHEN (pf.metadata->'configuration'->>'monitoringFrequencyMinutes') ~ '^[0-9]{1,6}$' THEN (pf.metadata->'configuration'->>'monitoringFrequencyMinutes')::int BETWEEN 1 AND 525600 ELSE false END
    AND COALESCE(ds.last_synced_at,'-infinity'::timestamptz) <= now()-make_interval(mins=>CASE WHEN (pf.metadata->'configuration'->>'monitoringFrequencyMinutes') ~ '^[0-9]{1,6}$' THEN (pf.metadata->'configuration'->>'monitoringFrequencyMinutes')::int ELSE 525600 END)
    AND EXISTS(SELECT 1 FROM competitor_product_mappings m JOIN tenant_competitors tc ON tc.tenant_id=m.tenant_id AND tc.global_competitor_id=m.global_competitor_id JOIN products p ON p.tenant_id=m.tenant_id AND p.product_id=m.product_id WHERE m.tenant_id=ds.tenant_id AND m.source_id=ds.source_id AND m.is_active AND m.comparison_confirmed AND tc.is_tracked AND p.deleted_at IS NULL)
    AND NOT EXISTS(SELECT 1 FROM ingestion_jobs j WHERE j.tenant_id=ds.tenant_id AND j.source_id=ds.source_id AND j.job_status IN ('QUEUED','PROCESSING') AND COALESCE(j.heartbeat_at,j.created_at)>now()-interval '30 minutes')
    AND NOT EXISTS(SELECT 1 FROM market_tracking_outbox o WHERE o.tenant_id=ds.tenant_id AND o.source_id=ds.source_id AND ((o.status<>'CANCELLED' AND o.worker_status<>'CANCELLED') OR o.last_error_code='COST_MARGIN_BLOCKED') AND (o.status='PENDING' OR o.created_at > now()-make_interval(mins=>CASE WHEN (pf.metadata->'configuration'->>'monitoringFrequencyMinutes') ~ '^[0-9]{1,6}$' THEN (pf.metadata->'configuration'->>'monitoringFrequencyMinutes')::int ELSE 525600 END)))
   ORDER BY ds.last_synced_at ASC NULLS FIRST,ds.source_id LIMIT 20`;
  let queued=0;
  for(const source of sources){
   await tx.$queryRaw`SELECT set_config('app.current_tenant_id',${source.tenant_id},true),set_config('app.current_user_id','',true)`;
   await tx.$executeRaw`UPDATE data_sources SET sync_frequency_minutes=${source.minutes} WHERE tenant_id=${source.tenant_id}::uuid AND source_id=${source.source_id}::uuid`;
   if(await requestCollection(tx,source.tenant_id,source.source_id,source.minutes,true))queued++;
  }
  return queued;
 },opts);
}
export async function dispatchMarketEvent(db:Database,redisUrl:string) {
 if(!COMPETITOR_AI_ACTIONS_ENABLED) return null;
 return db.$transaction(async tx=>{
  const events=await tx.$queryRaw<Event[]>`SELECT event_id,tenant_id,source_id,kind,competitor_id,attempts,dedupe_key FROM market_tracking_outbox WHERE status='PENDING' AND worker_status='QUEUED' AND next_attempt_at<=now() ORDER BY created_at,event_id FOR UPDATE SKIP LOCKED LIMIT 1`;
  const event=events[0];if(!event)return null;
  // Recheck current permissions/source eligibility immediately before publishing.
  const eligible=await tx.$queryRaw<Array<{allowed:boolean}>>`SELECT EXISTS(
   SELECT 1 FROM subscriptions s JOIN plan_features pf ON pf.plan_id=s.plan_id JOIN features f ON f.feature_id=pf.feature_id
   JOIN companies c ON c.tenant_id=s.tenant_id
   WHERE s.tenant_id=${event.tenant_id}::uuid AND s.status IN ('active','trialing') AND c.deleted_at IS NULL AND c.platform_status='active' AND f.feature_code='competitor_management'
   AND s.plan_id=(SELECT plan_id FROM subscriptions WHERE tenant_id=${event.tenant_id}::uuid AND status IN ('active','trialing') ORDER BY updated_at DESC,created_at DESC LIMIT 1)
   AND ((${event.dedupe_key} NOT LIKE 'sales-import:%' OR EXISTS(SELECT 1 FROM ingestion_jobs j JOIN data_sources ds ON ds.tenant_id=j.tenant_id AND ds.source_id=j.source_id JOIN import_staging_rows ir ON ir.tenant_id=j.tenant_id AND ir.job_id=j.job_id WHERE j.tenant_id=${event.tenant_id}::uuid AND j.job_id=(CASE WHEN ${event.dedupe_key} ~ '^sales-import:[0-9a-f-]{36}:' THEN split_part(${event.dedupe_key},':',2) ELSE NULL END)::uuid AND ds.source_type='documents' AND ir.committed_table='transactions' AND ir.validation_status='COMMITTED'))
   AND ${event.kind}='DISCOVERY' AND (${event.competitor_id}::uuid IS NULL OR EXISTS(SELECT 1 FROM tenant_competitors tc WHERE tc.tenant_id=${event.tenant_id}::uuid AND tc.global_competitor_id=${event.competitor_id}::uuid AND tc.is_tracked)) AND EXISTS(SELECT 1 FROM products WHERE tenant_id=${event.tenant_id}::uuid AND deleted_at IS NULL)
    OR ${event.kind}='COLLECTION' AND EXISTS(SELECT 1 FROM data_sources ds JOIN competitor_product_mappings m ON m.tenant_id=ds.tenant_id AND m.source_id=ds.source_id JOIN tenant_competitors tc ON tc.tenant_id=m.tenant_id AND tc.global_competitor_id=m.global_competitor_id JOIN products p ON p.tenant_id=m.tenant_id AND p.product_id=m.product_id
     WHERE ds.tenant_id=${event.tenant_id}::uuid AND ds.source_id=${event.source_id}::uuid AND ds.source_type IN ('website','WEB_SCRAPE') AND ds.is_active AND ds.policy_status='ALLOWED' AND ds.collector_key IS NOT NULL AND ds.collector_key NOT IN ('db_connector','api_connector') AND ds.approval_reference IS NOT NULL AND ds.approved_by IS NOT NULL AND ds.approved_at IS NOT NULL AND ds.privacy_reviewed_at IS NOT NULL AND m.is_active AND m.comparison_confirmed AND tc.is_tracked AND p.deleted_at IS NULL))) AS allowed`;
  if(!eligible[0]?.allowed){await tx.$executeRaw`UPDATE market_tracking_outbox SET status='CANCELLED',last_error_code='NO_LONGER_ELIGIBLE' WHERE event_id=${event.event_id}::uuid`;return {status:'CANCELLED',eventId:event.event_id,errorCode:'NO_LONGER_ELIGIBLE',tenantId:event.tenant_id,sourceId:event.source_id};}
  let messageId:string;
  try{
   const cost=event.kind==='COLLECTION'?await collectionCostDecision(event.tenant_id,event.source_id!):null;
   if(cost && !cost.allowed){
    await tx.$executeRaw`UPDATE market_tracking_outbox SET status='CANCELLED',last_error_code='COST_MARGIN_BLOCKED',worker_result=coalesce(worker_result,'{}'::jsonb)||jsonb_build_object('cost_guard_reason',${cost.reason}::text) WHERE event_id=${event.event_id}::uuid`;
    return {status:'CANCELLED',eventId:event.event_id,errorCode:'COST_MARGIN_BLOCKED',tenantId:event.tenant_id,sourceId:event.source_id,reason:cost.reason};
   }
   messageId=await publishMarketEvent(redisUrl,event.kind==='DISCOVERY'?(process.env.MARKET_DISCOVERY_STREAM_KEY||'market.discovery.requested'):(process.env.MARKET_SCRAPER_STREAM_KEY||'market.scrape.requested'),event);}
  catch(error){
   const failure=(error as Error)?.message; const code=['COST_GUARD_NOT_CONFIGURED','COST_GUARD_UNAVAILABLE'].includes(failure)?failure:'REDIS_PUBLISH_FAILED';
   const delay=Math.min(900,30*2**Math.min(event.attempts,5));
   await tx.$executeRaw`UPDATE market_tracking_outbox SET attempts=attempts+1,last_error_code=${code},next_attempt_at=now()+make_interval(secs=>${delay}) WHERE event_id=${event.event_id}::uuid`;
   return {status:'RETRYING',eventId:event.event_id,errorCode:code};
  }
  // Do not catch this write as a Redis failure: rollback leaves it pending and Redis dedupe prevents a second XADD.
  await tx.$executeRaw`UPDATE market_tracking_outbox SET status='PUBLISHED',published_at=now(),stream_message_id=${messageId},last_error_code=NULL,attempts=attempts+1 WHERE event_id=${event.event_id}::uuid`;
  return {status:'PUBLISHED',eventId:event.event_id};
 },opts);
}
