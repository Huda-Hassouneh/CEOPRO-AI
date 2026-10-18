import {createHash,randomUUID} from 'node:crypto';
import {prisma} from '../../../config/database.js';
import type {Prisma} from '../../../generated/prisma/client.js';
import {getFeatureAccessInfo} from '../../features/repo/usage.repo.js';
import {CompetitorError,type CompetitorScope} from '../types/competitors.types.js';
import type {SourceReview} from '../types/competitors.validation.js';
import {checkSourceRobots} from '../client/source-review.client.js';
import {monitoringMinutes} from '../service/competitors.policy.js';
import {marketTrackingConfig} from '../service/market-tracking.config.js';
import {requestCollection} from './market-tracking.requests.js';

async function reviewContext<T>(scope:CompetitorScope,approval:boolean,run:(tx:Prisma.TransactionClient,metadata:unknown)=>Promise<T>) {
  return prisma.$transaction(async tx=>{
    await tx.$queryRaw`SELECT set_config('app.current_tenant_id',${scope.tenantId},true),set_config('app.current_user_id',${scope.userId},true)`;
    const member=await tx.tenantUser.findFirst({where:{tenantId:scope.tenantId,userId:scope.userId,removedAt:null,platformStatus:'active'},include:{role:true}});
    const permissions=member?.role?.permissions as Record<string,unknown>|undefined;
    if(permissions?.all!==true && permissions?.['competitors.sources.review']!==true) throw new CompetitorError('FORBIDDEN');
    const access=await getFeatureAccessInfo(scope.tenantId,'competitor_management',tx);
    if(approval && !access.subscription) throw new CompetitorError('SUBSCRIPTION_NOT_FOUND');
    if(approval && !access.planFeature) throw new CompetitorError('FORBIDDEN');
    return run(tx,access.planFeature?.metadata);
  },{maxWait:10000,timeout:30000});
}
async function snapshot(tx:Prisma.TransactionClient,scope:CompetitorScope,competitorId:string,sourceId:string) {
  const competitor=await tx.tenant_competitors.findUnique({where:{tenant_id_global_competitor_id:{tenant_id:scope.tenantId,global_competitor_id:competitorId}}});
  const source=await tx.data_sources.findFirst({where:{tenant_id:scope.tenantId,source_id:sourceId}});
  const mappings=await tx.competitor_product_mappings.findMany({where:{tenant_id:scope.tenantId,source_id:sourceId,OR:[{is_active:true},{tracking_paused:true}]},orderBy:{mapping_id:'asc'},select:{mapping_id:true,global_competitor_id:true,competitor_product_url:true,is_active:true,tracking_paused:true,comparison_confirmed:true}});
  if(!competitor || !source || !mappings.some(m=>m.global_competitor_id===competitorId)) throw new CompetitorError('RESOURCE_NOT_FOUND');
  if(!['website','WEB_SCRAPE'].includes(source.source_type) || ![null,'standards'].includes(source.collector_key) || ![null,'WEB_SCRAPE','STRUCTURED_DATA'].includes(source.collection_method)) throw new CompetitorError('COMPETITOR_SOURCE_UNSUPPORTED');
  const urls=[...new Set([source.source_url,...mappings.map(m=>m.competitor_product_url)].filter((s):s is string=>!!s))];
  if(!source.source_url || mappings.some(m=>!m.competitor_product_url) || urls.length>100) throw new CompetitorError('COMPETITOR_SOURCE_UNSUPPORTED');
  const fingerprint=createHash('sha256').update(JSON.stringify({source,mappings,tracked:competitor.is_tracked})).digest('hex');
  return {source,competitor,mappings,urls,fingerprint};
}
export async function reviewCompetitorSource(scope:CompetitorScope,competitorId:string,sourceId:string,input:SourceReview) {
  const before=await reviewContext(scope,input.termsPermit,tx=>snapshot(tx,scope,competitorId,sourceId));
  if(input.termsPermit && !before.competitor.is_tracked) throw new CompetitorError('INVALID_PARAMETER');
  // No external I/O while a database transaction holds locks.
  const technical=input.termsPermit ? await checkSourceRobots(before.urls) : {allowed:null,reason:'TERMS_DISALLOW'};
  return reviewContext(scope,input.termsPermit,async(tx,metadata)=>{
    // Serialize with untrack, then take the source row before the queue lock,
    // matching applySchedule/dispatcher ordering to avoid lock inversions.
    await tx.$executeRawUnsafe('SELECT pg_advisory_xact_lock(hashtextextended($1,0))',`competitors-capacity:${scope.tenantId}`);
    await tx.$queryRaw`SELECT source_id FROM data_sources WHERE tenant_id=${scope.tenantId}::uuid AND source_id=${sourceId}::uuid FOR UPDATE`;
    await tx.$executeRawUnsafe('SELECT pg_advisory_xact_lock(hashtextextended($1,0))',`market-source:${sourceId}`);
    const current=await snapshot(tx,scope,competitorId,sourceId);
    if(current.fingerprint!==before.fingerprint) throw new CompetitorError('COMPETITOR_SOURCE_CHANGED');
    const status=!input.termsPermit || technical.allowed===false ? 'BLOCKED' : technical.allowed===true ? 'ALLOWED' : 'RESTRICTED';
    const now=new Date(),allowed=status==='ALLOWED',minutes=monitoringMinutes(metadata);
    const previous=current.source.technical_restrictions;
    const restrictions=previous && typeof previous==='object' && !Array.isArray(previous) ? previous : {};
    const decision={termsPermit:input.termsPermit,technicalAllowed:technical.allowed,reason:technical.reason,reference:input.reference,reviewerId:scope.userId,checkedAt:now.toISOString(),checkedPaths:current.urls.length};
    await tx.data_sources.update({where:{source_id:sourceId},data:{policy_status:status,policy_checked_at:now,
      collection_justification:technical.reason,technical_restrictions:{...restrictions,sourceReview:decision},
      approval_reference:allowed?input.reference:null,approved_by:allowed?scope.userId:null,approved_at:allowed?now:null,
      privacy_reviewed_at:input.privacyReviewed?now:null,retention_days:input.retentionDays,contains_personal_data:input.containsPersonalData,
      rate_limit_per_minute:input.rateLimitPerMinute,
      ...(allowed?{collection_method:current.source.collection_method || 'WEB_SCRAPE',collector_key:'standards',...(minutes!==null?{sync_frequency_minutes:minutes}:{})}:{})}});
    await tx.audit_logs.create({data:{tenant_id:scope.tenantId,user_id:scope.userId,action_type:'COLLECTION_POLICY_DECIDED',target_table:'data_sources',record_id:sourceId,
      changed_data_json:{...decision,status,competitorId,previousStatus:current.source.policy_status,retentionDays:input.retentionDays,containsPersonalData:input.containsPersonalData,rateLimitPerMinute:input.rateLimitPerMinute}}});
    const confirmed=current.mappings.some(mapping=>mapping.comparison_confirmed);
    const event=allowed && confirmed && current.source.is_active && minutes!==null ? await requestCollection(tx,scope.tenantId,sourceId,minutes,false,`source-review:${randomUUID()}`) : null;
    return {sourceId,policyStatus:status,technicalReason:technical.reason,collection:{...marketTrackingConfig(),eventId:event?.event_id??null,existingRequest:event?.status==='PUBLISHED',
      reason:!allowed?'SOURCE_NOT_APPROVED':!confirmed?'MATCH_UNCONFIRMED':!current.source.is_active?'SOURCE_INACTIVE':minutes===null?'CADENCE_NOT_CONFIGURED':event?'QUEUED':'NO_ELIGIBLE_COLLECTION'}};
  });
}
