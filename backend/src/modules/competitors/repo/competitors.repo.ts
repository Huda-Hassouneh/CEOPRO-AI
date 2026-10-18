import {randomUUID} from 'node:crypto';
import {context,permission,owned,lock} from './competitor-context.js';
import {candidateWorkflow} from './competitor-candidates.repo.js';
import {candidateRows} from './competitor-candidates.repo.js';
import {reviewCompetitorSource} from './competitor-source-review.repo.js';
import {requestDiscovery,requestCollection,requestCompetitorDiscovery} from './market-tracking.requests.js';
import {marketTrackingConfig} from '../service/market-tracking.config.js';
import type { Prisma } from "../../../generated/prisma/client.js";
import { CompetitorError, type CompetitorScope } from "../types/competitors.types.js";
import { websiteIdentity, type CompetitorCreate } from "../types/competitors.validation.js";
import { monitoringMinutes, priceComparison, priceActivity } from "../service/competitors.policy.js";

const localized = (value: unknown) => typeof value === 'string' ? { en:value,ar:value } : value;
const safeUrl = (value: string | null) => { try { if (!value) return null; websiteIdentity(value); return value; } catch { return null; } };
const maxAgeDays = () => { const raw=process.env.MARKET_INTELLIGENCE_MAX_SOURCE_AGE_DAYS; const n=Number(raw); return raw && Number.isFinite(n) && n > 0 ? n : null; };
async function capacity(tx:Prisma.TransactionClient, tenantId:string) {
  const rows=await tx.$queryRaw<Array<{current_usage:bigint;limit_value:number|null;is_unlimited:boolean;included:boolean}>>`SELECT * FROM public.competitor_capacity_for_tenant(${tenantId}::uuid)`;
  const row=rows[0]; if(!row) throw new Error('Competitor capacity unavailable');
  return {currentUsage:Number(row.current_usage),limit:row.limit_value,isUnlimited:row.is_unlimited,included:row.included,
    remaining:row.is_unlimited ? null : Math.max(0,(row.limit_value ?? 0)-Number(row.current_usage))};
}
async function requireCapacity(tx:Prisma.TransactionClient, tenantId:string) {
  const result=await capacity(tx,tenantId);
  if(!result.included || result.remaining !== null && result.remaining<1) throw new CompetitorError('COMPETITOR_CAPACITY_EXCEEDED',result);
}
function serialize(row:Awaited<ReturnType<typeof owned>>) {
  return {id:row.global_competitor_id,name:row.custom_alias || row.global_competitors.competitor_name,alias:row.custom_alias,
    website:safeUrl(row.global_competitors.website_url),industry:row.global_competitors.industry_sector,
    isTracked:row.is_tracked,addedAt:row.added_at};
}
async function applySchedule(tx:Prisma.TransactionClient, tenantId:string, id:string, metadata:unknown,requestKey?:string) {
  const minutes=monitoringMinutes(metadata);
  if(minutes===null) return {minutes:null,updatedSources:0,reason:'CADENCE_NOT_CONFIGURED'};
  const mappings=await tx.competitor_product_mappings.findMany({where:{tenant_id:tenantId,global_competitor_id:id,is_active:true,comparison_confirmed:true},select:{source_id:true}});
  const ids=[...new Set(mappings.map(row=>row.source_id).filter((value):value is string=>!!value))];
  // Never grant source approval, activate paused sources, or alter business connectors.
  const result=await tx.data_sources.updateMany({where:{tenant_id:tenantId,source_id:{in:ids},is_active:true,policy_status:'ALLOWED',
    approval_reference:{not:null},approved_at:{not:null},approved_by:{not:null},privacy_reviewed_at:{not:null},
    collector_key:{notIn:['db_connector','api_connector']},source_type:{in:['website','WEB_SCRAPE']}},data:{sync_frequency_minutes:minutes}});
  let queuedSources=0;
  for(const sourceId of ids) if(await requestCollection(tx,tenantId,sourceId,minutes,false,requestKey?`${requestKey}:${sourceId}`:undefined))queuedSources++;
  return {minutes,updatedSources:result.count,queuedSources,...marketTrackingConfig(),reason:result.count ? null : 'NO_APPROVED_SOURCE'};
}
export const competitorsRepo = {
  ...candidateWorkflow,
  reviewSource:reviewCompetitorSource,
  retryCollection:(scope:CompetitorScope,id:string,sourceId:string,eventId:string)=>context(scope,async(tx)=>{
    await owned(tx,scope.tenantId,id);
    const rows=await tx.$queryRaw<Array<{event_id:string|null;created:boolean;reason:string}>>`SELECT * FROM public.retry_market_collection(${scope.tenantId}::uuid,${id}::uuid,${sourceId}::uuid,${eventId}::uuid)`;
    const result=rows[0];
    if(!result?.event_id) throw new CompetitorError('COLLECTION_RETRY_UNAVAILABLE',{reason:result?.reason ?? 'SOURCE_NOT_ELIGIBLE'});
    return {eventId:result.event_id,created:result.created,reason:result.reason,...marketTrackingConfig()};
  },true),
  list:(scope:CompetitorScope,status:'active'|'inactive'|'all'='active')=>context(scope,async(tx,metadata,canEdit)=>{
    const rows=await tx.tenant_competitors.findMany({where:{tenant_id:scope.tenantId,...(status==='all'?{}:{is_tracked:status==='active'})},include:{global_competitors:true},orderBy:[{added_at:'desc'},{global_competitor_id:'asc'}]});
    return {competitors:rows.map(serialize),capacity:await capacity(tx,scope.tenantId),canEdit,monitoringFrequencyMinutes:monitoringMinutes(metadata)};
  },false,true),
  create:(scope:CompetitorScope,input:CompetitorCreate)=>context(scope,async(tx,metadata)=>{
    await lock(tx,scope.tenantId);
    const identity=websiteIdentity(input.website);
    // RLS exposes global identities and this tenant's private ones, never another tenant's private catalog.
    const host=new URL(input.website).hostname.replace(/^www\./,'');
    const candidates=await tx.global_competitors.findMany({where:{AND:[{OR:[{visibility:'GLOBAL'},{visibility:'PRIVATE',added_by_tenant_id:scope.tenantId}]},{OR:[{website_identity_key:identity},{website_url:{contains:host,mode:'insensitive'}}]}]}});
    const matches=candidates.filter(row=>{try{return !!row.website_url && websiteIdentity(row.website_url)===identity;}catch{return false;}});
    if(matches.length>1) throw new CompetitorError('COMPETITOR_IDENTITY_AMBIGUOUS');
    let global=matches[0];
    if(global) {
      const existing=await tx.tenant_competitors.findUnique({where:{tenant_id_global_competitor_id:{tenant_id:scope.tenantId,global_competitor_id:global.global_competitor_id}}});
      if(!existing?.is_tracked) await requireCapacity(tx,scope.tenantId);
    } else {
      await requireCapacity(tx,scope.tenantId);
      global=await tx.global_competitors.create({data:{competitor_name:input.name,website_url:input.website,industry_sector:input.industry || null,
        website_identity_key:identity,visibility:'PRIVATE',added_by_tenant_id:scope.tenantId}});
    }
    const where={tenant_id_global_competitor_id:{tenant_id:scope.tenantId,global_competitor_id:global.global_competitor_id}};
    const linked=await tx.tenant_competitors.findUnique({where});
    const row=linked ? await tx.tenant_competitors.update({where,data:{is_tracked:true},include:{global_competitors:true}})
      :await tx.tenant_competitors.create({data:{tenant_id:scope.tenantId,global_competitor_id:global.global_competitor_id,custom_alias:input.name,is_tracked:true},include:{global_competitors:true}});
    return {...serialize(row),monitoring:await applySchedule(tx,scope.tenantId,row.global_competitor_id,metadata),discovery:await requestCompetitorDiscovery(tx,scope.tenantId,row.global_competitor_id)};
  },true),
  update:(scope:CompetitorScope,id:string,alias:string|null)=>context(scope,async tx=>{
    await lock(tx,scope.tenantId); await owned(tx,scope.tenantId,id);
    const row=await tx.tenant_competitors.update({where:{tenant_id_global_competitor_id:{tenant_id:scope.tenantId,global_competitor_id:id}},data:{custom_alias:alias || null},include:{global_competitors:true}});
    return serialize(row);
  },true),
  track:(scope:CompetitorScope,id:string,isTracked:boolean)=>context(scope,async(tx,metadata)=>{
    await lock(tx,scope.tenantId); const current=await owned(tx,scope.tenantId,id);
    if(isTracked && !current.is_tracked) await requireCapacity(tx,scope.tenantId);
    const row=await tx.tenant_competitors.update({where:{tenant_id_global_competitor_id:{tenant_id:scope.tenantId,global_competitor_id:id}},data:{is_tracked:isTracked},include:{global_competitors:true}});
    return {...serialize(row),monitoring:isTracked?await applySchedule(tx,scope.tenantId,id,metadata):null,discovery:isTracked?await requestCompetitorDiscovery(tx,scope.tenantId,id):null};
  },true,!isTracked),
  discover:(scope:CompetitorScope)=>context(scope,async tx=>requestDiscovery(tx,scope.tenantId),true),
  cancelDiscovery:(scope:CompetitorScope,id:string,eventId:string)=>context(scope,async tx=>{
    await owned(tx,scope.tenantId,id);
    const rows=await tx.$queryRaw<Array<{event_id:string}>>`UPDATE market_tracking_outbox SET worker_status='CANCELLED',worker_finished_at=now(),worker_error_code='USER_CANCELLED'
      WHERE tenant_id=${scope.tenantId}::uuid AND event_id=${eventId}::uuid AND kind='DISCOVERY'
       AND (competitor_id IS NULL OR competitor_id=${id}::uuid) AND worker_status IN ('QUEUED','RUNNING') RETURNING event_id`;
    return {cancelled:rows.length>0};
  },true,true),
  schedule:(scope:CompetitorScope,id:string)=>context(scope,async(tx,metadata)=>{
    const row=await owned(tx,scope.tenantId,id); if(!row.is_tracked) throw new CompetitorError('INVALID_PARAMETER');
    return applySchedule(tx,scope.tenantId,id,metadata);
  },true),
  confirm:(scope:CompetitorScope,id:string,mappingId:string,confirmed:boolean)=>context(scope,async(tx,metadata)=>{
    await lock(tx,scope.tenantId);
    const competitor=await owned(tx,scope.tenantId,id); if(!competitor.is_tracked) throw new CompetitorError('INVALID_PARAMETER');
    const result=await tx.competitor_product_mappings.updateMany({where:{tenant_id:scope.tenantId,global_competitor_id:id,mapping_id:mappingId,is_active:true},data:{comparison_confirmed:confirmed}});
    if(!result.count) throw new CompetitorError('RESOURCE_NOT_FOUND');
    return {mappingId,comparisonConfirmed:confirmed,...(confirmed?{monitoring:await applySchedule(tx,scope.tenantId,id,metadata,`match-confirm:${randomUUID()}`)}:{})};
  },true),
  profile:(scope:CompetitorScope,id:string)=>context(scope,async(tx,metadata,canEdit)=>{
    const competitor=await owned(tx,scope.tenantId,id);
    const candidates=await candidateRows(tx,scope.tenantId,id);
    const previousMappings=await tx.competitor_product_mappings.findMany({where:{tenant_id:scope.tenantId,global_competitor_id:id,is_active:false,tracking_paused:false},orderBy:{created_at:'desc'},take:30,select:{mapping_id:true,product_id:true,competitor_product_url:true,created_at:true,_count:{select:{competitor_prices:true}}}});
    const mappings=await tx.competitor_product_mappings.findMany({where:{tenant_id:scope.tenantId,global_competitor_id:id,OR:[{is_active:true},{tracking_paused:true}],products:{deleted_at:null}},
      include:{products:true,data_sources:{include:{ingestion_jobs:{where:{tenant_id:scope.tenantId},orderBy:[{created_at:'desc'},{job_id:'desc'}],take:1,select:{job_status:true,rows_failed:true,next_attempt_at:true,ended_at:true}}}},competitor_prices:{orderBy:[{observed_at:'desc'},{competitor_price_id:'desc'}],take:100}}});
    const now=new Date(), maxAge=maxAgeDays(); const activity:Array<ReturnType<typeof priceActivity>[number] & {type:string;productName:unknown}>=[];
    const mappedProducts=mappings.map(mapping=>{
      const source=mapping.data_sources;
      const sourceAllowed=!source || source.is_active && source.policy_status==='ALLOWED' && !!source.approved_at && !!source.approval_reference && !!source.approved_by && !!source.privacy_reviewed_at;
      const rawComparison=priceComparison(mapping.competitor_prices,mapping.products.currency,mapping.products.current_price,mapping.comparison_confirmed,now,maxAge,sourceAllowed);
      const comparison=competitor.is_tracked ? rawComparison : {...rawComparison,competitorPrice:null,priceDifference:null,priceDifferencePercent:null,reason:'TRACKING_PAUSED'};
      if(mapping.comparison_confirmed && sourceAllowed) for(const row of priceActivity(mapping.competitor_prices,now,maxAge)) activity.push({...row,type:'PRICE_CHANGE',productName:localized(mapping.products.product_name)});
      return {id:mapping.product_id,mappingId:mapping.mapping_id,name:localized(mapping.products.product_name),ourPrice:Number.isFinite(Number(mapping.products.current_price)) && Number(mapping.products.current_price)>=0 ? Number(mapping.products.current_price) : null,
        currency:mapping.products.currency,...comparison,url:safeUrl(mapping.competitor_product_url),sku:mapping.competitor_product_sku,comparisonConfirmed:mapping.comparison_confirmed,
        ownIdentity:{name:mapping.products.product_name,brand:mapping.products.brand,gtin:mapping.products.gtin},
        collectedPrice:mapping.competitor_prices[0]?{amount:Number(mapping.competitor_prices[0].scraped_price),currency:mapping.competitor_prices[0].currency,observedAt:mapping.competitor_prices[0].observed_at,isAvailable:mapping.competitor_prices[0].is_available}:null,
        preview:candidates.find(c=>c.product_id===mapping.product_id && c.product_url===mapping.competitor_product_url)?.evidence ?? null,
        monitoring:source?{sourceId:source.source_id,policyStatus:source.policy_status,isActive:source.is_active,frequencyMinutes:source.sync_frequency_minutes,lastSyncedAt:source.last_synced_at,latestJob:source.ingestion_jobs[0]?{status:source.ingestion_jobs[0].job_status,failedRows:source.ingestion_jobs[0].rows_failed,retryAt:source.ingestion_jobs[0].next_attempt_at,endedAt:source.ingestion_jobs[0].ended_at}:null}:null};
    });
    const collectionRows=await tx.$queryRaw<Array<{source_id:string;event_id:string;status:string;worker_status:string;worker_error_code:string|null;worker_attempts:number;worker_heartbeat_at:Date|null;created_at:Date;published_at:Date|null;worker_result:unknown;legacy_failed:boolean}>>`
      SELECT o.source_id,o.event_id,o.status,o.worker_status,o.worker_error_code,o.worker_attempts,o.worker_heartbeat_at,o.created_at,o.published_at,o.worker_result,
       (o.worker_status='QUEUED' AND o.status='PUBLISHED' AND o.worker_attempts=0 AND o.worker_started_at IS NULL AND o.worker_error_code IS NULL AND j.job_status='FAILED' AND j.created_at>=o.published_at AND NOT EXISTS(SELECT 1 FROM ingestion_jobs a WHERE a.tenant_id=o.tenant_id AND a.source_id=o.source_id AND a.job_status IN ('QUEUED','PROCESSING'))) AS legacy_failed
      FROM (SELECT DISTINCT ON(q.source_id) q.* FROM market_tracking_outbox q
       WHERE q.tenant_id=${scope.tenantId}::uuid AND q.kind='COLLECTION' AND q.source_id=ANY(${mappings.map(m=>m.source_id).filter(Boolean)}::uuid[])
       ORDER BY q.source_id,q.created_at DESC,q.event_id DESC) o
      LEFT JOIN LATERAL(SELECT i.job_status,i.created_at FROM ingestion_jobs i WHERE i.tenant_id=o.tenant_id AND i.source_id=o.source_id ORDER BY i.created_at DESC,i.job_id DESC LIMIT 1) j ON true`;
    const collections=new Map(collectionRows.map(row=>[row.source_id,{...row,worker_status:row.legacy_failed?'FAILED':row.worker_status,worker_error_code:row.legacy_failed?'PREVIOUS_COLLECTION_FAILED':row.worker_error_code}]));
    const sources=[...new Map(mappings.filter(m=>m.data_sources).map(m=>[m.source_id,m.data_sources!])).values()].map(source=>({
      id:source.source_id,name:source.source_name,url:safeUrl(source.source_url),policyStatus:source.policy_status,isActive:source.is_active,
      reviewSupported:!!source.source_url && ['website','WEB_SCRAPE'].includes(source.source_type) && [null,'standards'].includes(source.collector_key) && [null,'WEB_SCRAPE','STRUCTURED_DATA'].includes(source.collection_method),
      approvedAt:source.approved_at,approvalReference:source.approval_reference,checkedAt:source.policy_checked_at,reason:source.collection_justification,
      retentionDays:source.retention_days,containsPersonalData:source.contains_personal_data,rateLimitPerMinute:source.rate_limit_per_minute,
      collection:collections.get(source.source_id) ?? null,
      canRetryCollection:canEdit && competitor.is_tracked && source.is_active && source.policy_status==='ALLOWED' && collections.get(source.source_id)?.worker_status==='FAILED' && collections.get(source.source_id)?.status!=='CANCELLED',
      mappedProducts:mappings.filter(m=>m.source_id===source.source_id).length
    }));
    activity.sort((a,b)=>b.date.getTime()-a.date.getTime());
    const events=await tx.$queryRaw<Array<{event_id:string;kind:string;status:string;source_id:string|null;created_at:Date;published_at:Date|null;last_error_code:string|null;competitor_id:string|null;worker_status:string;worker_heartbeat_at:Date|null;worker_result:unknown;worker_error_code:string|null}>>`
      SELECT event_id,kind,status,source_id,created_at,published_at,last_error_code,competitor_id,worker_status,worker_heartbeat_at,worker_result,worker_error_code FROM market_tracking_outbox
      WHERE tenant_id=${scope.tenantId}::uuid AND NOT(status='CANCELLED' AND last_error_code='NO_LONGER_ELIGIBLE' AND dedupe_key LIKE 'sales-import:%') AND ((kind='DISCOVERY' AND (competitor_id IS NULL OR competitor_id=${id}::uuid)) OR source_id=ANY(${mappings.map(m=>m.source_id).filter(Boolean)}::uuid[])) ORDER BY created_at DESC LIMIT 5`;
    return {...serialize(competitor),candidates,previousMappings,canEdit,canReviewSources:await permission(tx,scope,'competitors.sources.review'),sources,trackingIntegration:{...marketTrackingConfig(),events:events.map(event=>({...event,...(event.kind==='COLLECTION' && collections.get(event.source_id ?? '')?.event_id===event.event_id ? collections.get(event.source_id ?? '') : {})}))},monitoringFrequencyMinutes:monitoringMinutes(metadata),maxSourceAgeDays:maxAge,mappedProducts,activity:activity.slice(0,100),
      metrics:[],strengths:[],weaknesses:[],presence:{current:[],previous:[]}};
  })
};
