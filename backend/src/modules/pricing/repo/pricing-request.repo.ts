import {prisma} from '../../../config/database.js';
import {Prisma} from '../../../generated/prisma/client.js';
import {releaseFeatureUsageInTransaction,reserveFeatureUsageInTransaction} from '../../features/repo/usage.repo.js';
import {persistPricingRecommendation} from './pricing.repo.js';
import {PricingRequestError} from '../service/pricing.errors.js';
import type {PricingProductContext,PricingRecommendationResult} from '../types/pricing.types.js';

type Context={tenantId:string;userId:string};
type Row={tenant_id:string;user_id:string;request_id:string;product_id:string;usage_record_id:string;status:string;
  response:PricingRecommendationResult|null;created_at:Date;expires_at:Date};
async function context(tx:Prisma.TransactionClient,c:Context){
  await tx.$executeRaw`SELECT set_config('app.current_tenant_id',${c.tenantId},true),set_config('app.current_user_id',${c.userId},true)`;
}
async function lock(tx:Prisma.TransactionClient,c:Context){
  await tx.$executeRaw`SELECT pg_advisory_xact_lock(hashtextextended(${'metered-usage:'+c.tenantId+':ai_pricing'},0))`;
}
async function expired(tx:Prisma.TransactionClient,c:Context){
  const rows=await tx.$queryRaw<Row[]>`SELECT * FROM public.pricing_requests WHERE tenant_id=${c.tenantId}::uuid AND status='pending' AND expires_at<=now() FOR UPDATE`;
  for(const row of rows){
    await releaseFeatureUsageInTransaction(tx,c.tenantId,'ai_pricing',1,row.usage_record_id);
    await tx.$executeRaw`UPDATE public.pricing_requests SET status='failed',failure_code='REQUEST_EXPIRED',completed_at=now() WHERE tenant_id=${c.tenantId}::uuid AND user_id=${row.user_id}::uuid AND request_id=${row.request_id}::uuid`;
  }
}
// Commit recovery separately so a subsequent quota/conflict error cannot roll
// back expired-lease refunds. This runs on generate and history reads.
export async function recoverPricingRequests(c:Context){
  await prisma.$transaction(async tx=>{await context(tx,c);await lock(tx,c);await expired(tx,c);});
}
function replay(row:Row,productId:string){
  if(row.product_id!==productId)throw new PricingRequestError('REQUEST_CONFLICT');
  if(row.status==='completed'&&row.response)return row.response;
  throw new PricingRequestError(row.status==='pending'?'REQUEST_PENDING':'REQUEST_FAILED');
}
export async function lookupPricingRequest(c:Context,requestId:string,productId:string){
  return prisma.$transaction(async tx=>{await context(tx,c);
    const rows=await tx.$queryRaw<Row[]>`SELECT * FROM public.pricing_requests WHERE tenant_id=${c.tenantId}::uuid AND user_id=${c.userId}::uuid AND request_id=${requestId}::uuid`;
    return rows[0]?replay(rows[0],productId):null;
  });
}
export async function beginPricingRequest(c:Context,requestId:string,productId:string){
  return prisma.$transaction(async tx=>{await context(tx,c);await lock(tx,c);
    const same=await tx.$queryRaw<Row[]>`SELECT * FROM public.pricing_requests WHERE tenant_id=${c.tenantId}::uuid AND user_id=${c.userId}::uuid AND request_id=${requestId}::uuid`;
    if(same[0])return {cached:replay(same[0],productId)};
    const pending=await tx.$queryRaw<Row[]>`SELECT * FROM public.pricing_requests WHERE tenant_id=${c.tenantId}::uuid AND product_id=${productId}::uuid AND status='pending'`;
    if(pending.length)throw new PricingRequestError('REQUEST_PENDING');
    const reserved=await reserveFeatureUsageInTransaction(tx,c.tenantId,'ai_pricing',1,true);
    await tx.$executeRaw`INSERT INTO public.pricing_requests(tenant_id,user_id,request_id,product_id,usage_record_id,status)
      VALUES(${c.tenantId}::uuid,${c.userId}::uuid,${requestId}::uuid,${productId}::uuid,${reserved.usageRecordId}::uuid,'pending')`;
    return {cached:null};
  });
}
export async function failPricingRequest(c:Context,requestId:string,code:string){
  await prisma.$transaction(async tx=>{await context(tx,c);await lock(tx,c);
    const rows=await tx.$queryRaw<Row[]>`SELECT * FROM public.pricing_requests WHERE tenant_id=${c.tenantId}::uuid AND user_id=${c.userId}::uuid AND request_id=${requestId}::uuid FOR UPDATE`;
    const row=rows[0];if(!row||row.status!=='pending')return;
    await releaseFeatureUsageInTransaction(tx,c.tenantId,'ai_pricing',1,row.usage_record_id);
    await tx.$executeRaw`UPDATE public.pricing_requests SET status='failed',failure_code=${code},completed_at=now() WHERE tenant_id=${c.tenantId}::uuid AND user_id=${c.userId}::uuid AND request_id=${requestId}::uuid`;
  });
}
export async function finishPricingRequest(c:Context,requestId:string,product:PricingProductContext,
  result:Omit<PricingRecommendationResult,'evidence_id'|'outcome_id'>):Promise<PricingRecommendationResult>{
  return prisma.$transaction(async tx=>{await context(tx,c);await lock(tx,c);
    const rows=await tx.$queryRaw<Row[]>`SELECT * FROM public.pricing_requests WHERE tenant_id=${c.tenantId}::uuid AND user_id=${c.userId}::uuid AND request_id=${requestId}::uuid AND expires_at>now() FOR UPDATE`;
    const row=rows[0];if(!row||row.status!=='pending')throw new PricingRequestError('REQUEST_EXPIRED');
    const current=await tx.$queryRaw<Array<{current_price:Prisma.Decimal;cost_price:Prisma.Decimal|null;currency:string;version:number}>>`
      SELECT current_price,cost_price,currency,version FROM public.products WHERE tenant_id=${c.tenantId}::uuid AND product_id=${product.productId}::uuid AND deleted_at IS NULL FOR SHARE`;
    const p=current[0];if(!p||p.version!==product.version||Number(p.current_price)!==product.currentPrice||
      (p.cost_price===null?null:Number(p.cost_price))!==product.costPrice||p.currency!==product.currency)throw new PricingRequestError('SOURCE_CHANGED');
    // Revoked mappings/source permissions or edited selected observations must
    // not be committed as authorized inputs after a slow provider call.
    const selectedSources=[...result.sources,...result.reference_sources];
    if(selectedSources.length){
      const prices=await tx.competitor_prices.findMany({where:{tenant_id:c.tenantId,
        competitor_price_id:{in:selectedSources.map(s=>s.competitor_price_id)},is_available:true,is_exact_data:true,source_status:'ALLOWED',
        competitor_product_mappings:{product_id:product.productId,is_active:true,tracking_paused:false,comparison_confirmed:true,
          tenant_competitors:{is_tracked:true},OR:[{source_id:null},{data_sources:{is_active:true,policy_status:'ALLOWED'}}]}},
        select:{competitor_price_id:true,scraped_price:true,currency:true,observed_at:true}});
      if(prices.length!==selectedSources.length||!selectedSources.every(s=>prices.some(p=>p.competitor_price_id===s.competitor_price_id&&
        Number(p.scraped_price)===s.original_price&&p.currency===s.original_currency&&p.observed_at.toISOString()===s.observed_at)))throw new PricingRequestError('SOURCE_CHANGED');
    }
    const saved=await persistPricingRecommendation({...c,productId:product.productId,status:result.status,action:result.action,
      currentPrice:result.current_price,suggestedPrice:result.suggested_price,confidenceScore:result.confidence_score,
      explanationText:result.explanation,matchedCompetitorCount:result.matched_competitor_count,
      guardrailClamped:result.guardrail_clamped,marginGuardrailClamped:result.margin_guardrail_clamped,
      audit:JSON.parse(JSON.stringify(result)),sourceRecordIds:{competitor_price_ids:result.sources.map(s=>s.competitor_price_id),
        reference_competitor_price_ids:result.reference_sources.map(s=>s.competitor_price_id),
        mapping_ids:selectedSources.map(s=>s.mapping_id),competitor_ids:selectedSources.map(s=>s.competitor_id)}},tx);
    const response={...result,evidence_id:saved.evidenceId,outcome_id:saved.outcomeId};
    if(!response.charged)await releaseFeatureUsageInTransaction(tx,c.tenantId,'ai_pricing',1,row.usage_record_id);
    await tx.$executeRaw`UPDATE public.pricing_requests SET status='completed',charged=${response.charged},response=${JSON.stringify(response)}::jsonb,completed_at=now()
      WHERE tenant_id=${c.tenantId}::uuid AND user_id=${c.userId}::uuid AND request_id=${requestId}::uuid`;
    return response;
  });
}
export async function pricingHistory(c:Context,productId:string){
  await recoverPricingRequests(c);
  return prisma.$transaction(async tx=>{await context(tx,c);
    const rows=await tx.$queryRaw<Row[]>`SELECT * FROM public.pricing_requests WHERE tenant_id=${c.tenantId}::uuid AND product_id=${productId}::uuid AND status='completed' ORDER BY created_at DESC,request_id DESC LIMIT 20`;
    return rows.map(r=>r.response!);
  });
}
