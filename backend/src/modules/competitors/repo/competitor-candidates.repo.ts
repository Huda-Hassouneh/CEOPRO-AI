import {context,owned,lock} from './competitor-context.js';
import type {Prisma} from '../../../generated/prisma/client.js';
import {CompetitorError,type CompetitorScope} from '../types/competitors.types.js';
import {productUrlInScope} from '../service/product-url.js';
import {checkProductPreview} from '../client/product-preview.client.js';
import type {ProductLink} from '../types/competitors.validation.js';

export type CandidateRow={candidate_id:string;product_id:string;product_url:string;title:string;discovery_score:unknown;status:string;evidence:unknown;checked_at:Date|null};
export async function candidateRows(tx:Prisma.TransactionClient,tenantId:string,competitorId:string,productId:string|null=null) {
  return tx.$queryRaw<CandidateRow[]>`SELECT candidate_id,product_id,product_url,title,discovery_score,status,evidence,checked_at
    FROM (SELECT c.*,row_number() OVER(PARTITION BY product_id ORDER BY CASE WHEN status='SELECTED' THEN 0 ELSE 1 END,discovery_score DESC,last_seen_at DESC,candidate_id) AS rank
      FROM competitor_product_candidates c WHERE tenant_id=${tenantId}::uuid AND global_competitor_id=${competitorId}::uuid AND status<>'REJECTED'
       AND (${productId}::uuid IS NULL OR product_id=${productId}::uuid)) ranked
    WHERE rank<=10 ORDER BY product_id,rank LIMIT 500`;
}
async function audit(tx:Prisma.TransactionClient,scope:CompetitorScope,id:string,action:string,facts:Prisma.InputJsonValue) {
  await tx.audit_logs.create({data:{tenant_id:scope.tenantId,user_id:scope.userId,action_type:action,target_table:'competitor_product_mappings',record_id:id,changed_data_json:facts}});
}
async function productLock(tx:Prisma.TransactionClient,scope:CompetitorScope,competitorId:string,productId:string) {
  await lock(tx,scope.tenantId);
  await tx.$executeRawUnsafe('SELECT pg_advisory_xact_lock(hashtextextended($1,0))',`market-mapping:${scope.tenantId}:${competitorId}:${productId}`);
}
async function previewSnapshot(tx:Prisma.TransactionClient,scope:CompetitorScope,id:string,mappingId:string) {
  const competitor=await owned(tx,scope.tenantId,id);
  const mapping=await tx.competitor_product_mappings.findFirst({where:{tenant_id:scope.tenantId,global_competitor_id:id,mapping_id:mappingId,is_active:true,products:{deleted_at:null}},include:{products:true,data_sources:true}});
  if(!mapping) throw new CompetitorError('RESOURCE_NOT_FOUND');
  const source=mapping.data_sources;
  if(!competitor.is_tracked || !source?.is_active || source.policy_status!=='ALLOWED' || !source.approved_at || !source.approved_by || !source.approval_reference || !source.privacy_reviewed_at || source.collector_key!=='standards')
    throw new CompetitorError('COMPETITOR_SOURCE_UNSUPPORTED',{reason:'APPROVE_SOURCE_BEFORE_PREVIEW'});
  const url=productUrlInScope(mapping.competitor_product_url||'',competitor.global_competitors.website_url||'');
  if(!url) throw new CompetitorError('INVALID_PARAMETER');
  const fingerprint=JSON.stringify({mappingId,url,source,product:mapping.products});
  return {mapping,source,url,fingerprint,scopeUrl:competitor.global_competitors.website_url};
}

export const candidateWorkflow={
  productCandidates:(scope:CompetitorScope,id:string,productId:string)=>context(scope,async tx=>{
    await owned(tx,scope.tenantId,id);return candidateRows(tx,scope.tenantId,id,productId);
  }),
  catalogProducts:(scope:CompetitorScope,id:string,query:{search:string;page:number})=>context(scope,async tx=>{
    await owned(tx,scope.tenantId,id);
    const term='%'+query.search.replace(/[\\%_]/g,'\\$&')+'%';
    const products=await tx.$queryRaw<Array<{id:string;name:unknown;brand:unknown;gtin:string|null;mappingId:string|null;url:string|null}>>`
      SELECT p.product_id AS id,p.product_name AS name,p.brand,p.gtin,m.mapping_id AS "mappingId",m.competitor_product_url AS url
      FROM products p LEFT JOIN competitor_product_mappings m ON m.tenant_id=p.tenant_id AND m.product_id=p.product_id
        AND m.global_competitor_id=${id}::uuid AND (m.is_active OR m.tracking_paused)
      WHERE p.tenant_id=${scope.tenantId}::uuid AND p.deleted_at IS NULL
       AND (${query.search}='' OR p.product_name->>'en' ILIKE ${term} OR p.product_name->>'ar' ILIKE ${term} OR p.sku ILIKE ${term} OR p.gtin ILIKE ${term})
      ORDER BY p.product_id LIMIT 26 OFFSET ${(query.page-1)*25}`;
    return {products:products.slice(0,25),hasMore:products.length>25,page:query.page};
  }),
  linkProduct:(scope:CompetitorScope,id:string,input:ProductLink)=>context(scope,async tx=>{
    await productLock(tx,scope,id,input.productId);
    const competitor=await owned(tx,scope.tenantId,id);
    if(!competitor.is_tracked) throw new CompetitorError('INVALID_PARAMETER');
    const product=await tx.products.findFirst({where:{tenant_id:scope.tenantId,product_id:input.productId,deleted_at:null}});
    const url=productUrlInScope(input.url,competitor.global_competitors.website_url||'');
    if(!product || !url) throw new CompetitorError('INVALID_PARAMETER');
    const previous=await tx.competitor_product_mappings.findFirst({where:{tenant_id:scope.tenantId,global_competitor_id:id,product_id:input.productId,OR:[{is_active:true},{tracking_paused:true}]}});
    if((previous?.mapping_id??null)!==input.expectedMappingId) throw new CompetitorError('COMPETITOR_SOURCE_CHANGED');
    if(previous?.competitor_product_url===url) return {mappingId:previous.mapping_id,sourceId:previous.source_id,changed:false};
    if(previous) await tx.competitor_product_mappings.update({where:{mapping_id:previous.mapping_id},data:{is_active:false,tracking_paused:false,comparison_confirmed:false}});
    // A fresh source deliberately inherits no approval or credentials from the
    // previous URL. Approval always checks the actual selected product path.
    const source=await tx.data_sources.create({data:{tenant_id:scope.tenantId,source_name:`Competitor product: ${competitor.custom_alias||competitor.global_competitors.competitor_name}`,source_type:'WEB_SCRAPE',source_url:url,collector_key:'standards',collection_method:'STRUCTURED_DATA',policy_status:'RESTRICTED'}});
    const mapping=await tx.competitor_product_mappings.create({data:{tenant_id:scope.tenantId,global_competitor_id:id,product_id:input.productId,competitor_product_url:url,source_id:source.source_id}});
    await tx.$executeRaw`UPDATE competitor_product_candidates SET status='DISCOVERED' WHERE tenant_id=${scope.tenantId}::uuid AND global_competitor_id=${id}::uuid AND product_id=${input.productId}::uuid AND status='SELECTED'`;
    await tx.$executeRaw`INSERT INTO competitor_product_candidates(tenant_id,global_competitor_id,product_id,product_url,status)
      VALUES(${scope.tenantId}::uuid,${id}::uuid,${input.productId}::uuid,${url},'SELECTED')
      ON CONFLICT(tenant_id,global_competitor_id,product_id,product_url) DO UPDATE SET status='SELECTED'`;
    await audit(tx,scope,mapping.mapping_id,'COMPETITOR_PRODUCT_LINKED',{competitorId:id,productId:input.productId,previousMappingId:previous?.mapping_id??null,url});
    return {mappingId:mapping.mapping_id,sourceId:source.source_id,changed:true,reason:'SOURCE_REVIEW_REQUIRED'};
  },true),
  rejectCandidate:(scope:CompetitorScope,id:string,candidateId:string)=>context(scope,async tx=>{
    const rows=await tx.$queryRaw<Array<{product_id:string;product_url:string}>>`SELECT product_id,product_url FROM competitor_product_candidates WHERE tenant_id=${scope.tenantId}::uuid AND global_competitor_id=${id}::uuid AND candidate_id=${candidateId}::uuid`;
    const candidate=rows[0];if(!candidate)throw new CompetitorError('RESOURCE_NOT_FOUND');
    await productLock(tx,scope,id,candidate.product_id);await owned(tx,scope.tenantId,id);
    await tx.$executeRaw`UPDATE competitor_product_candidates SET status='REJECTED' WHERE tenant_id=${scope.tenantId}::uuid AND candidate_id=${candidateId}::uuid`;
    const mappings=await tx.competitor_product_mappings.findMany({where:{tenant_id:scope.tenantId,global_competitor_id:id,product_id:candidate.product_id,competitor_product_url:candidate.product_url,OR:[{is_active:true},{tracking_paused:true}]}});
    for(const mapping of mappings){
      await tx.competitor_product_mappings.update({where:{mapping_id:mapping.mapping_id},data:{is_active:false,tracking_paused:false,comparison_confirmed:false}});
      await audit(tx,scope,mapping.mapping_id,'COMPETITOR_MATCH_REJECTED',{candidateId,url:candidate.product_url});
    }
    return {candidateId,rejected:true};
  },true),
  previewProduct:async(scope:CompetitorScope,id:string,mappingId:string)=>{
    const before=await context(scope,tx=>previewSnapshot(tx,scope,id,mappingId),true);
    const name=before.mapping.products.product_name as Record<string,string>|string;
    const target={product_name:typeof name==='string'?name:name?.en||name?.ar||'',product_brand:before.mapping.products.brand,product_name_aliases:typeof name==='string'?[name]:Object.values(name||{}),gtin:before.mapping.products.gtin,external_sku:before.mapping.competitor_product_sku};
    const evidence=await checkProductPreview({url:before.url,target,collectorConfig:before.source.collector_config,scopeUrl:before.scopeUrl});
    return context(scope,async tx=>{
      await productLock(tx,scope,id,before.mapping.product_id);
      const current=await previewSnapshot(tx,scope,id,mappingId);
      if(current.fingerprint!==before.fingerprint)throw new CompetitorError('COMPETITOR_SOURCE_CHANGED');
      // Preview is evidence only: it cannot approve, confirm, enqueue or write a
      // market price. Collection still uses the existing authorized worker.
      const checkedAt=new Date().toISOString();
      await tx.$executeRaw`INSERT INTO competitor_product_candidates(tenant_id,global_competitor_id,product_id,product_url,status,evidence,checked_at)
        VALUES(${scope.tenantId}::uuid,${id}::uuid,${before.mapping.product_id}::uuid,${before.url},'SELECTED',${JSON.stringify(evidence)}::jsonb,${checkedAt}::timestamptz)
        ON CONFLICT(tenant_id,global_competitor_id,product_id,product_url) DO UPDATE SET evidence=EXCLUDED.evidence,checked_at=EXCLUDED.checked_at`;
      return {...evidence,checkedAt};
    },true);
  }
};
