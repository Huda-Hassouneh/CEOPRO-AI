import {createHash,randomUUID} from 'node:crypto';
import {prisma} from '../../config/database.js';
import type {Prisma} from '../../generated/prisma/client.js';
import {getFeatureAccessInfo} from '../features/repo/usage.repo.js';
import {requestBusinessInsights,type Finding} from './client.js';
export class RecommendationError extends Error{constructor(public code:string){super(code);}}
export type Scope={tenantId:string;userId:string};
export async function context(tx:Prisma.TransactionClient,c:Scope){await tx.$executeRaw`SELECT set_config('app.current_tenant_id',${c.tenantId},true),set_config('app.current_user_id',${c.userId},true)`;}
async function lock(tx:Prisma.TransactionClient,c:Scope){await tx.$executeRaw`SELECT pg_advisory_xact_lock(hashtextextended(${'business-recommendations:'+c.tenantId},0))`;}
async function access(c:Scope){const a=await getFeatureAccessInfo(c.tenantId,'business_recommendations');if(!a.subscription||a.planFeature?.feature.type!=='boolean')throw new RecommendationError('FEATURE_NOT_INCLUDED');}
function stable(value:unknown):unknown{
 if(Array.isArray(value))return value.map(stable).sort((a,b)=>JSON.stringify(a).localeCompare(JSON.stringify(b)));
 if(value&&typeof value==='object')return Object.fromEntries(Object.entries(value).filter(([k])=>!['generated_at','until'].includes(k)).sort(([a],[b])=>a.localeCompare(b)).map(([k,v])=>[k,stable(v)]));
 return value;
}
function localizeFinding(f:Finding){
 const names=typeof f.product_name==='object'&&f.product_name!==null?f.product_name:{};
 const label=typeof names.ar==='string'?names.ar:typeof names.en==='string'?names.en:typeof f.product_name==='string'?f.product_name:'هذا المنتج';
 const rules:Record<string,string>={overpriced_sales_forecast_down:`سعر ${label} أعلى من السوق، مع تراجع المبيعات والطلب المتوقع. راجع السعر والقيمة المقدمة قبل اتخاذ قرار.`,
  overpriced_sales_down:`سعر ${label} أعلى من السوق والمبيعات تتراجع. قارن السعر الحالي بالأسعار المؤكدة وراجع أسباب التراجع؛ هذه علاقة محتملة وليست إثباتًا للسبب.`,
  overpriced_negative_feedback:`سعر ${label} أعلى من السوق وتقييمات العملاء سلبية. راجع شكاوى العملاء قبل تعديل السعر.`,
  feedback_sales_down:`تراجعت المبيعات بالتزامن مع آراء سلبية حول ${label}. راجع ملاحظات العملاء وجودة الخدمة قبل تغيير السعر.`,
  underpriced_healthy_demand:`سعر ${label} أقل من السوق مع مؤشرات طلب جيدة. يمكنك دراسة اختبار زيادة محدودة ومراقبة النتائج دون ضمان أثرها.`,
  demand_growing:`توقعات أحد الأيام المقبلة أعلى من وتيرة المبيعات اليومية المسجلة لمنتج ${label}. راجع تغطية المخزون دون اعتبارها إجمالي شهر كامل.`,
  demand_cooling:`توقعات أحد الأيام المقبلة أقل من وتيرة المبيعات اليومية المسجلة لمنتج ${label}. راجع تخطيط المخزون والعروض.`,
  review_excess_stock:`المخزون المسجل لمنتج ${label} أعلى من توقع مكتمل يغطي 30 يومًا. راجع كميات الطلب المقبلة؛ هذا لا يثبت ضرورة إيقاف المنتج.`};
 let ar=rules[f.rule_id];
 if(f.rule_id.startsWith('competitor_price_drop:'))ar=`تزامن انخفاض سعر منافس مع تراجع مبيعات ${label}. راجع التوقيت والأسعار؛ التزامن لا يثبت علاقة سببية.`;
 if(f.rule_id.startsWith('category_gap:'))ar=`توجد فئة منتجات لدى منافسين متابَعين وغير موجودة في كتالوجك. ادرس ملاءمتها لنشاطك قبل إضافتها: ${String((f.evidence.detector_facts as Record<string,unknown>)?.category??'')}.`;
 if(!ar)ar='توجد مؤشرات تستحق المراجعة. راجع الأدلة قبل اتخاذ إجراء.';
 return {...f,message_i18n:{en:f.message,ar}};
}
export async function listRecommendations(c:Scope,state='active',page=1){await access(c);
 return prisma.$transaction(async tx=>{await context(tx,c);const where=state==='all'?undefined:state;
  const rows=await tx.business_recommendations.findMany({where:{tenant_id:c.tenantId,...(where?{state:where}:{})},orderBy:[{updated_at:'desc'},{recommendation_id:'desc'}],skip:(page-1)*20,take:20});
  const total=await tx.business_recommendations.count({where:{tenant_id:c.tenantId,...(where?{state:where}:{})}});
  return {recommendations:rows,page,total,page_size:20};
 });
}
export async function setRecommendationState(c:Scope,id:string,state:'active'|'dismissed'){
 await access(c);return prisma.$transaction(async tx=>{await context(tx,c);
  const result=await tx.business_recommendations.updateMany({where:{tenant_id:c.tenantId,recommendation_id:id,state:{not:'resolved'}},data:{state}});
  if(!result.count)throw new RecommendationError('NOT_FOUND');return {state};
 });
}
export async function recommendationEvidence(c:Scope,id:string){await access(c);
 return prisma.$transaction(async tx=>{await context(tx,c);const r=await tx.business_recommendations.findFirst({where:{tenant_id:c.tenantId,recommendation_id:id}});
  if(!r)throw new RecommendationError('NOT_FOUND');return tx.evidence_records.findFirst({where:{tenant_id:c.tenantId,evidence_id:r.evidence_id}});
 });
}
export async function refreshRecommendations(c:Scope,requestId:string,authorization:string){
 await access(c);
 const cached=await prisma.$transaction(async tx=>{await context(tx,c);await lock(tx,c);
  await tx.business_recommendation_runs.updateMany({where:{tenant_id:c.tenantId,status:'pending',expires_at:{lte:new Date()}},data:{status:'failed'}});
  const row=await tx.business_recommendation_runs.findUnique({where:{tenant_id_user_id_request_id:{tenant_id:c.tenantId,user_id:c.userId,request_id:requestId}}});
  if(row?.status==='completed')return row.response;
  if(row)throw new RecommendationError(row.status==='pending'?'REQUEST_PENDING':'REQUEST_FAILED');
  if(await tx.business_recommendation_runs.count({where:{tenant_id:c.tenantId,status:'pending'}}))throw new RecommendationError('REQUEST_PENDING');
  await tx.business_recommendation_runs.create({data:{tenant_id:c.tenantId,user_id:c.userId,request_id:requestId,status:'pending'}});return null;
 });
 if(cached)return cached;
 try{
  const response=await requestBusinessInsights(authorization);
  return await prisma.$transaction(async tx=>{await context(tx,c);await lock(tx,c);
   const run=await tx.business_recommendation_runs.findUnique({where:{tenant_id_user_id_request_id:{tenant_id:c.tenantId,user_id:c.userId,request_id:requestId}}});
   if(run?.status!=='pending'||run.expires_at.getTime()<=Date.now())throw new RecommendationError('REQUEST_EXPIRED');
   const currentAccess=await getFeatureAccessInfo(c.tenantId,'business_recommendations',tx);
   if(!currentAccess.subscription||!currentAccess.planFeature)throw new RecommendationError('FEATURE_NOT_INCLUDED');
   const productIds=[...new Set(response.recommendations.flatMap(f=>f.product_id?[f.product_id]:[]))];
   const valid=await tx.products.count({where:{tenant_id:c.tenantId,product_id:{in:productIds},deleted_at:null}});
   if(valid!==productIds.length)throw new RecommendationError('INVALID_AI_RESULT');
   const keys=new Set<string>();let changed=0;
   for(const finding of response.recommendations){
    if(keys.has(finding.logical_key))throw new RecommendationError('INVALID_AI_RESULT');keys.add(finding.logical_key);
    const body=localizeFinding(finding),fingerprint=createHash('sha256').update(JSON.stringify(stable(body))).digest('hex');
    const old=await tx.business_recommendations.findUnique({where:{tenant_id_logical_key:{tenant_id:c.tenantId,logical_key:finding.logical_key}}});
    const newEpisode=!old||old.state==='resolved';let evidenceId=old?.evidence_id;
    if(!old||old.source_fingerprint!==fingerprint){
     changed++;
     const evidence=await tx.evidence_records.create({data:{tenant_id:c.tenantId,category:'RECOMMENDATION',source_module:'business_recommendations',metric_name:finding.rule_id.slice(0,100),
      metric_value_json:JSON.parse(JSON.stringify(body)),source_record_ids:{product_id:finding.product_id,logical_key:finding.logical_key},explanation_text:body.message_i18n.en},select:{evidence_id:true}});evidenceId=evidence.evidence_id;
    }
    const record=await tx.business_recommendations.upsert({where:{tenant_id_logical_key:{tenant_id:c.tenantId,logical_key:finding.logical_key}},
     create:{tenant_id:c.tenantId,logical_key:finding.logical_key,product_id:finding.product_id,rule_id:finding.rule_id,category:finding.category,priority:finding.priority,
      body:JSON.parse(JSON.stringify(body)),source_fingerprint:fingerprint,evidence_id:evidenceId!},
     update:{product_id:finding.product_id,priority:finding.priority,body:JSON.parse(JSON.stringify(body)),source_fingerprint:fingerprint,evidence_id:evidenceId!,
      last_seen_at:new Date(),...(newEpisode?{state:'active',episode_id:randomUUID()}:{}),...(old?.source_fingerprint!==fingerprint?{updated_at:new Date()}: {})}});
    if(record.state==='active'&&finding.priority==='high')await tx.tenantNotificationOutbox.createMany({data:[{tenantId:c.tenantId,eventType:'BUSINESS_RECOMMENDATION_READY',
      dedupeKey:`recommendation:${record.recommendation_id}:${record.episode_id}`,payload:{recommendationId:record.recommendation_id}}],skipDuplicates:true});
   }
   if(response.complete)await tx.business_recommendations.updateMany({where:{tenant_id:c.tenantId,logical_key:{notIn:[...keys]},state:{not:'resolved'}},data:{state:'resolved',updated_at:new Date()}});
   const summary={request_id:requestId,generated_at:response.generated_at,total:response.recommendations.length,changed_count:changed,complete:response.complete,products_checked:response.products_checked};
   await tx.business_recommendation_runs.update({where:{tenant_id_user_id_request_id:{tenant_id:c.tenantId,user_id:c.userId,request_id:requestId}},data:{status:'completed',response:summary}});return summary;
  },{timeout:30000});
 }catch(error){
  await prisma.$transaction(async tx=>{await context(tx,c);await tx.business_recommendation_runs.updateMany({where:{tenant_id:c.tenantId,user_id:c.userId,request_id:requestId,status:'pending'},data:{status:'failed'}});});throw error;
 }
}
